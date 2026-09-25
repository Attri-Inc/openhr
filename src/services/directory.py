"""Employee-directory use cases. Depends only on repository protocols (Dependency Inversion).

This is the single place the employment-lifecycle invariants are enforced:
a status only moves along an allowed edge of the state machine, an exit always
carries a date, and a new joiner is given their leave entitlements in the same
DB transaction that creates them — so nobody can exist without a leave bucket.
"""

from src.days import format_units
from src.domain.constants import (
    EMPLOYMENT_TRANSITIONS,
    EMPLOYMENT_TYPES,
    LEAVE_POLICY,
    TRACKED_LEAVE_TYPES,
    UNITS_PER_DAY,
)
from src.domain.dates import require_iso_date
from src.domain.errors import ConflictError, NotFoundError, ValidationError
from src.infrastructure.database import Database
from src.infrastructure.identity import new_id, now_iso
from src.money import format_lpa, format_minor
from src.repositories.protocols import (
    AuditWriter,
    EmployeeReader,
    EmployeeWriter,
    LeaveWriter,
)


def present(employee: dict) -> dict:
    """Add the formatted, derived fields every caller wants — in one place."""
    return {
        **employee,
        "ctc": format_minor(employee.get("ctc_minor") or 0),
        "ctc_lpa": format_lpa(employee.get("ctc_minor") or 0),
    }


class EmployeeService:
    def __init__(
        self,
        db: Database,
        reader: EmployeeReader,
        writer: EmployeeWriter,
        leave: LeaveWriter,
        audit: AuditWriter,
    ):
        self._db = db
        self._reader = reader
        self._writer = writer
        self._leave = leave
        self._audit = audit

    # -- reads -----------------------------------------------------------------

    async def resolve(self, identifier: str) -> dict | None:
        return await self._reader.get(identifier)

    async def require(self, identifier: str, label: str = "Employee") -> dict:
        employee = await self._reader.get(identifier)
        if not employee:
            raise NotFoundError(f"{label} not found: {identifier}")
        return employee

    async def list_employees(
        self,
        department: str | None = None,
        status: str | None = None,
        manager: str | None = None,
        include_exited: bool = False,
        q: str | None = None,
    ) -> list[dict]:
        manager_id = None
        if manager:
            manager_id = (await self.require(manager, "Manager"))["id"]
        rows = await self._reader.list_rows(department, status, manager_id, include_exited, q)
        return [present(row) for row in rows]

    async def get_employee(self, identifier: str) -> dict | None:
        employee = await self._reader.get(identifier)
        if not employee:
            return None
        manager = (
            await self._reader.get_by_id(employee["manager_id"])
            if employee.get("manager_id")
            else None
        )
        reports = await self._reader.direct_reports(employee["id"])
        return {
            **present(employee),
            "manager": {"id": manager["id"], "code": manager["code"], "name": manager["name"]}
            if manager
            else None,
            "direct_reports": reports,
            "direct_report_count": len(reports),
        }

    async def org_chart(self, root: str | None = None, depth: int = 3) -> dict:
        """The reporting tree below `root` (or every top-level manager)."""
        if root:
            top = [await self.require(root, "Root employee")]
        else:
            everyone = await self._reader.list_rows(None, None, None, False, None)
            top = [row for row in everyone if not row.get("manager_id")]

        async def branch(employee: dict, remaining: int) -> dict:
            node = {
                "id": employee["id"],
                "code": employee["code"],
                "name": employee["name"],
                "designation": employee["designation"],
                "department": employee["department"],
            }
            if remaining <= 0:
                return node
            children = await self._reader.direct_reports(employee["id"])
            node["reports"] = [await branch(child, remaining - 1) for child in children]
            return node

        return {"depth": depth, "roots": [await branch(person, depth) for person in top]}

    # -- writes ----------------------------------------------------------------

    async def create(
        self,
        code: str,
        name: str,
        email: str,
        department: str,
        designation: str,
        joined_on: str,
        manager: str | None = None,
        location: str | None = None,
        employment_type: str = "full_time",
        band: str | None = None,
        status: str = "probation",
        ctc_minor: int = 0,
        date_of_birth: str | None = None,
        actor: str = "mcp",
    ) -> dict:
        if employment_type not in EMPLOYMENT_TYPES:
            raise ValidationError(
                f"Invalid employment_type '{employment_type}'. "
                f"Must be one of: {', '.join(sorted(EMPLOYMENT_TYPES))}"
            )
        if status not in ("probation", "active"):
            raise ValidationError("A new employee starts as 'probation' or 'active'")
        # bool is a subclass of int — reject it so True cannot land as 1 paisa.
        if isinstance(ctc_minor, bool) or not isinstance(ctc_minor, int) or ctc_minor < 0:
            raise ValidationError("ctc_minor must be a non-negative integer (paise)")
        require_iso_date(joined_on, "joined_on")
        if date_of_birth:
            require_iso_date(date_of_birth, "date_of_birth")

        manager_row = None
        if manager:
            manager_row = await self.require(manager, "Manager")
            if manager_row["status"] == "exited":
                raise ValidationError(
                    f"Manager {manager_row['code']} · {manager_row['name']} has exited"
                )

        employee_id = new_id("emp")
        now = now_iso()
        employee = {
            "id": employee_id,
            "code": code,
            "name": name,
            "email": email,
            "department": department,
            "designation": designation,
            "manager_id": manager_row["id"] if manager_row else None,
            "location": location,
            "employment_type": employment_type,
            "band": band,
            "status": status,
            "joined_on": joined_on,
            "date_of_birth": date_of_birth,
            "ctc_minor": ctc_minor,
            "created_at": now,
            "updated_at": now,
        }
        year = require_iso_date(joined_on, "joined_on").year
        async with self._db.unit_of_work() as conn:
            await self._writer.insert(conn, employee)  # raises ConflictError on duplicate
            # A joiner without leave buckets could never take leave. Grant them in
            # the same transaction so the two can never diverge.
            for leave_type in sorted(TRACKED_LEAVE_TYPES):
                await self._leave.upsert_entitlement(
                    conn,
                    {
                        "id": new_id("ent"),
                        "employee_id": employee_id,
                        "leave_type": leave_type,
                        "year": year,
                        "entitled_units": LEAVE_POLICY[leave_type]["annual_quota_days"]
                        * UNITS_PER_DAY,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            await self._audit.append(
                conn,
                {
                    "id": new_id("aud"),
                    "actor": actor,
                    "action": "create_employee",
                    "object_type": "employee",
                    "object_id": employee_id,
                    "details": f"Created {code} · {name} — {designation}, {department}",
                    "created_at": now_iso(),
                },
            )
        return (await self.get_employee(employee_id)) or {}

    async def update_status(
        self,
        identifier: str,
        status: str,
        effective_date: str | None = None,
        reason: str | None = None,
        actor: str = "mcp",
    ) -> dict:
        employee = await self.require(identifier)
        current = employee["status"]
        allowed = EMPLOYMENT_TRANSITIONS.get(current, frozenset())
        if status == current:
            raise ConflictError(f"{employee['code']} is already '{current}'")
        if status not in allowed:
            allowed_text = ", ".join(sorted(allowed)) or "nothing — it is terminal"
            raise ValidationError(
                f"Cannot move {employee['code']} from '{current}' to '{status}'. "
                f"Allowed from '{current}': {allowed_text}."
            )

        exited_on = employee.get("exited_on")
        if status == "exited":
            if not effective_date:
                raise ValidationError("effective_date (the last working day) is required to exit")
            require_iso_date(effective_date, "effective_date")
            if effective_date < employee["joined_on"]:
                raise ValidationError(
                    f"effective_date {effective_date} is before the joining date "
                    f"{employee['joined_on']}"
                )
            exited_on = effective_date
        elif current == "notice" and status == "active":
            exited_on = None  # resignation withdrawn

        now = now_iso()
        async with self._db.unit_of_work() as conn:
            await self._writer.set_status(conn, employee["id"], status, exited_on, now)
            await self._audit.append(
                conn,
                {
                    "id": new_id("aud"),
                    "actor": actor,
                    "action": "update_employment_status",
                    "object_type": "employee",
                    "object_id": employee["id"],
                    "details": f"{employee['code']} · {employee['name']}: {current} → {status}"
                    + (f" ({reason})" if reason else ""),
                    "created_at": now_iso(),
                },
            )
        return (await self.get_employee(employee["id"])) or {}

    # -- helpers used by other services ---------------------------------------

    @staticmethod
    def describe_entitlement(units: int) -> str:
        return format_units(units)
