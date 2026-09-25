"""Leave use cases — the balance ledger at the heart of OpenHR.

This is the single place the leave invariants are enforced, so any future caller
(REST, UI, another agent) cannot diverge from the rules:

1. Leave is counted in integer half-day units. No floats.
2. A request **reserves** balance the moment it is raised. `pending` and
   `approved` both consume; `declined` and `cancelled` release. Approving a
   pending request therefore moves no balance at all — the reservation was
   already made — which is what makes double-spending structurally impossible.
3. A tracked leave type can never be overdrawn. The check runs inside the same
   Unit of Work as the insert.
4. Nobody can be on two overlapping live requests.
5. A decided request is never rewritten. Corrections are a `cancel`, which
   releases the balance and leaves the original visible.
"""

from src.days import days_to_units, format_units
from src.domain.constants import (
    LEAVE_POLICY,
    LEAVE_TRANSITIONS,
    TRACKED_LEAVE_TYPES,
)
from src.domain.dates import calendar_days, leave_year_of, require_iso_date, require_range
from src.domain.errors import ConflictError, NotFoundError, ValidationError
from src.infrastructure.database import Database
from src.infrastructure.identity import new_id, now_iso
from src.repositories.protocols import AuditWriter, EmployeeReader, LeaveReader, LeaveWriter

DECISIONS: dict[str, str] = {"approve": "approved", "decline": "declined"}


def present_request(row: dict) -> dict:
    """Attach the formatted duration every caller wants, in one place."""
    return {**row, "days": format_units(row["units"]), "leave_type_name": _type_name(row)}


def _type_name(row: dict) -> str:
    policy = LEAVE_POLICY.get(row.get("leave_type", ""))
    return policy["name"] if policy else row.get("leave_type", "")


class LeaveService:
    def __init__(
        self,
        db: Database,
        employees: EmployeeReader,
        reader: LeaveReader,
        writer: LeaveWriter,
        audit: AuditWriter,
    ):
        self._db = db
        self._employees = employees
        self._reader = reader
        self._writer = writer
        self._audit = audit

    # -- internals -------------------------------------------------------------

    async def _require_employee(self, identifier: str) -> dict:
        employee = await self._employees.get(identifier)
        if not employee:
            raise NotFoundError(f"Employee not found: {identifier}")
        return employee

    async def _available_units(
        self, employee_id: str, leave_type: str, year: int
    ) -> tuple[int, int, int]:
        """(entitled, consumed, available) for a tracked type, in half-day units."""
        entitlements = {
            row["leave_type"]: row["entitled_units"]
            for row in await self._reader.entitlement_rows(employee_id, year)
        }
        entitled = int(entitlements.get(leave_type, 0))
        consumed = await self._reader.consumed_units(employee_id, leave_type, year)
        return entitled, consumed, entitled - consumed

    # -- reads -----------------------------------------------------------------

    async def balance(self, identifier: str, year: int | None = None) -> dict:
        employee = await self._require_employee(identifier)
        year = year or int(now_iso()[:4])
        entitlements = {
            row["leave_type"]: int(row["entitled_units"])
            for row in await self._reader.entitlement_rows(employee["id"], year)
        }
        balances = []
        for leave_type in sorted(LEAVE_POLICY):
            policy = LEAVE_POLICY[leave_type]
            consumed = await self._reader.consumed_units(employee["id"], leave_type, year)
            entitled = entitlements.get(leave_type, 0)
            available = entitled - consumed
            balances.append(
                {
                    "leave_type": leave_type,
                    "name": policy["name"],
                    "tracked": policy["tracked"],
                    "paid": policy["paid"],
                    "entitled_units": entitled,
                    "entitled": format_units(entitled),
                    "consumed_units": consumed,
                    "consumed": format_units(consumed),
                    "available_units": available if policy["tracked"] else None,
                    "available": format_units(available) if policy["tracked"] else "not rationed",
                }
            )
        return {
            "employee": {
                "id": employee["id"],
                "code": employee["code"],
                "name": employee["name"],
                "department": employee["department"],
            },
            "year": year,
            "balances": balances,
        }

    async def list_requests(
        self,
        employee: str | None = None,
        leave_type: str | None = None,
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> dict:
        employee_id = None
        if employee:
            employee_id = (await self._require_employee(employee))["id"]
        if leave_type and leave_type not in LEAVE_POLICY:
            raise ValidationError(
                f"Unknown leave_type '{leave_type}'. Must be one of: {', '.join(sorted(LEAVE_POLICY))}"
            )
        if date_from:
            require_iso_date(date_from, "date_from")
        if date_to:
            require_iso_date(date_to, "date_to")
        rows, total = await self._reader.list_requests(
            employee_id, leave_type, status, date_from, date_to, limit, offset
        )
        return {
            "items": [present_request(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    async def calendar(self, date_from: str, date_to: str | None = None) -> dict:
        date_to = date_to or date_from
        require_range(date_from, date_to)
        rows = await self._reader.on_leave_between(date_from, date_to)
        by_department: dict[str, list[dict]] = {}
        for row in rows:
            by_department.setdefault(row["department"], []).append(present_request(row))
        return {
            "from": date_from,
            "to": date_to,
            "on_leave_count": len(rows),
            "by_department": by_department,
            "entries": [present_request(row) for row in rows],
        }

    async def get_request(self, request_id: str) -> dict | None:
        row = await self._reader.get_request(request_id)
        return present_request(row) if row else None

    # -- writes ----------------------------------------------------------------

    async def request(
        self,
        employee: str,
        leave_type: str,
        start_date: str,
        end_date: str,
        days: float,
        reason: str,
        actor: str = "mcp",
    ) -> dict:
        if leave_type not in LEAVE_POLICY:
            raise ValidationError(
                f"Unknown leave_type '{leave_type}'. Must be one of: {', '.join(sorted(LEAVE_POLICY))}"
            )
        if not reason or not reason.strip():
            raise ValidationError("reason is required — leave is an auditable record")
        require_range(start_date, end_date)

        try:
            units = days_to_units(days)
        except (TypeError, ValueError) as e:
            raise ValidationError(
                f"days must be a whole or half number of days, got {days!r}"
            ) from e
        if units <= 0:
            raise ValidationError("days must be greater than zero")
        span_units = calendar_days(start_date, end_date) * 2
        if units > span_units:
            raise ValidationError(
                f"{format_units(units)} claimed but {start_date}..{end_date} spans only "
                f"{format_units(span_units)}"
            )

        person = await self._require_employee(employee)
        if person["status"] == "exited":
            raise ValidationError(f"{person['code']} · {person['name']} has exited")

        clashes = await self._reader.overlapping(person["id"], start_date, end_date, None)
        if clashes:
            first = clashes[0]
            raise ConflictError(
                f"Overlaps an existing {first['status']} {first['leave_type']} request "
                f"({first['id']}: {first['start_date']}..{first['end_date']})"
            )

        year = leave_year_of(start_date)
        if leave_type in TRACKED_LEAVE_TYPES:
            entitled, consumed, available = await self._available_units(
                person["id"], leave_type, year
            )
            if units > available:
                raise ValidationError(
                    f"Insufficient {LEAVE_POLICY[leave_type]['name']} balance for "
                    f"{person['code']} in {year}: {format_units(available)} available "
                    f"({format_units(entitled)} entitled, {format_units(consumed)} already "
                    f"pending or approved), {format_units(units)} requested"
                )

        request_id = new_id("lv")
        now = now_iso()
        async with self._db.unit_of_work() as conn:
            await self._writer.insert_request(
                conn,
                {
                    "id": request_id,
                    "employee_id": person["id"],
                    "leave_type": leave_type,
                    "start_date": start_date,
                    "end_date": end_date,
                    "units": units,
                    "reason": reason.strip(),
                    "status": "pending",
                    "requested_by": actor,
                    "created_at": now,
                },
            )
            await self._audit.append(
                conn,
                {
                    "id": new_id("aud"),
                    "actor": actor,
                    "action": "request_leave",
                    "object_type": "leave_request",
                    "object_id": request_id,
                    "details": f"{person['code']} requested {format_units(units)} "
                    f"{LEAVE_POLICY[leave_type]['name']} ({start_date}..{end_date})",
                    "created_at": now_iso(),
                },
            )
        return (await self.get_request(request_id)) or {}

    async def decide(
        self,
        request_id: str,
        decision: str,
        decided_by: str,
        note: str | None = None,
        actor: str = "mcp",
    ) -> dict:
        if decision not in DECISIONS:
            raise ValidationError(f"decision must be 'approve' or 'decline', got '{decision}'")
        target = DECISIONS[decision]
        request = await self._reader.get_request(request_id)
        if not request:
            raise NotFoundError(f"Leave request not found: {request_id}")
        if target not in LEAVE_TRANSITIONS.get(request["status"], frozenset()):
            raise ConflictError(
                f"Leave request {request_id} is '{request['status']}' and cannot be {target}"
            )
        approver = await self._employees.get(decided_by)
        if not approver:
            raise NotFoundError(f"Approver not found: {decided_by}")
        if approver["id"] == request["employee_id"]:
            raise ValidationError("An employee cannot decide their own leave request")

        now = now_iso()
        async with self._db.unit_of_work() as conn:
            await self._writer.decide_request(conn, request_id, target, approver["id"], now, note)
            await self._audit.append(
                conn,
                {
                    "id": new_id("aud"),
                    "actor": actor,
                    "action": "decide_leave_request",
                    "object_type": "leave_request",
                    "object_id": request_id,
                    "details": f"{approver['code']} {target} {request['employee_code']}'s "
                    f"{format_units(request['units'])} {request['leave_type']} leave"
                    + (f" — {note}" if note else ""),
                    "created_at": now_iso(),
                },
            )
        return (await self.get_request(request_id)) or {}

    async def cancel(self, request_id: str, reason: str, actor: str = "mcp") -> dict:
        if not reason or not reason.strip():
            raise ValidationError("reason is required to cancel a leave request")
        request = await self._reader.get_request(request_id)
        if not request:
            raise NotFoundError(f"Leave request not found: {request_id}")
        if "cancelled" not in LEAVE_TRANSITIONS.get(request["status"], frozenset()):
            raise ConflictError(
                f"Leave request {request_id} is '{request['status']}' and cannot be cancelled"
            )

        now = now_iso()
        async with self._db.unit_of_work() as conn:
            await self._writer.cancel_request(conn, request_id, now, reason.strip())
            await self._audit.append(
                conn,
                {
                    "id": new_id("aud"),
                    "actor": actor,
                    "action": "cancel_leave_request",
                    "object_type": "leave_request",
                    "object_id": request_id,
                    "details": f"Cancelled {request['employee_code']}'s "
                    f"{format_units(request['units'])} {request['leave_type']} leave "
                    f"({request['start_date']}..{request['end_date']}): {reason.strip()}",
                    "created_at": now_iso(),
                },
            )
        return (await self.get_request(request_id)) or {}

    async def grant_entitlement(
        self,
        employee: str,
        leave_type: str,
        year: int,
        entitled_days: float,
        actor: str = "mcp",
    ) -> dict:
        """Set a leave bucket — used to credit comp-off and to open a new leave year."""
        if leave_type not in TRACKED_LEAVE_TYPES:
            raise ValidationError(
                f"'{leave_type}' is not a tracked leave type, so it has no entitlement. "
                f"Tracked types: {', '.join(sorted(TRACKED_LEAVE_TYPES))}"
            )
        try:
            units = days_to_units(entitled_days)
        except (TypeError, ValueError) as e:
            raise ValidationError(
                f"entitled_days must be a whole or half number of days, got {entitled_days!r}"
            ) from e
        if units < 0:
            raise ValidationError("entitled_days cannot be negative")
        person = await self._require_employee(employee)
        consumed = await self._reader.consumed_units(person["id"], leave_type, year)
        if units < consumed:
            raise ConflictError(
                f"Cannot set entitlement to {format_units(units)}: {person['code']} has already "
                f"used or reserved {format_units(consumed)} of {leave_type} in {year}"
            )

        now = now_iso()
        async with self._db.unit_of_work() as conn:
            await self._writer.upsert_entitlement(
                conn,
                {
                    "id": new_id("ent"),
                    "employee_id": person["id"],
                    "leave_type": leave_type,
                    "year": year,
                    "entitled_units": units,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            await self._audit.append(
                conn,
                {
                    "id": new_id("aud"),
                    "actor": actor,
                    "action": "grant_leave_entitlement",
                    "object_type": "employee",
                    "object_id": person["id"],
                    "details": f"{person['code']} {leave_type} {year} entitlement set to "
                    f"{format_units(units)}",
                    "created_at": now_iso(),
                },
            )
        return await self.balance(person["id"], year)
