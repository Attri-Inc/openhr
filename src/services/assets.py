"""Asset-custody use cases.

The custody invariant — *an asset has at most one holder at a time* — is enforced
twice on purpose: by a partial unique index in the schema (so the engine refuses
a second open assignment even under a race) and by an explicit check here (so the
caller gets a sentence instead of an IntegrityError).

Custody history is append-only: a return closes the open assignment row, it never
deletes it, so "who had this laptop in March" stays answerable forever.
"""

from src.domain.constants import ASSET_CONDITIONS
from src.domain.dates import require_iso_date
from src.domain.errors import ConflictError, NotFoundError, ValidationError
from src.infrastructure.database import Database
from src.infrastructure.identity import new_id, now_iso
from src.money import format_minor
from src.repositories.protocols import AssetReader, AssetWriter, AuditWriter, EmployeeReader

# A return in one of these conditions cannot go straight back into stock.
REPAIR_CONDITIONS: frozenset[str] = frozenset({"poor", "damaged"})


def present(asset: dict) -> dict:
    return {**asset, "value": format_minor(asset.get("value_minor") or 0)}


class AssetService:
    def __init__(
        self,
        db: Database,
        employees: EmployeeReader,
        reader: AssetReader,
        writer: AssetWriter,
        audit: AuditWriter,
    ):
        self._db = db
        self._employees = employees
        self._reader = reader
        self._writer = writer
        self._audit = audit

    async def _require_asset(self, identifier: str) -> dict:
        asset = await self._reader.get(identifier)
        if not asset:
            raise NotFoundError(f"Asset not found: {identifier}")
        return asset

    async def _require_employee(self, identifier: str) -> dict:
        employee = await self._employees.get(identifier)
        if not employee:
            raise NotFoundError(f"Employee not found: {identifier}")
        return employee

    @staticmethod
    def _require_condition(condition: str) -> str:
        if condition not in ASSET_CONDITIONS:
            raise ValidationError(
                f"Invalid condition '{condition}'. "
                f"Must be one of: {', '.join(sorted(ASSET_CONDITIONS))}"
            )
        return condition

    # -- reads -----------------------------------------------------------------

    async def list_assets(
        self,
        status: str | None = None,
        category: str | None = None,
        holder: str | None = None,
        q: str | None = None,
    ) -> dict:
        holder_id = None
        if holder:
            holder_id = (await self._require_employee(holder))["id"]
        rows = await self._reader.list_rows(status, category, holder_id, q)
        items = [present(row) for row in rows]
        total_value = sum(row.get("value_minor") or 0 for row in rows)
        return {
            "items": items,
            "total": len(items),
            "total_value_minor": total_value,
            "total_value": format_minor(total_value),
        }

    async def employee_assets(self, employee: str, include_returned: bool = False) -> dict:
        person = await self._require_employee(employee)
        rows = await self._reader.assignments_for(person["id"], include_returned)
        held = [row for row in rows if row.get("returned_on") is None]
        outstanding = sum(row.get("value_minor") or 0 for row in held)
        return {
            "employee": {"id": person["id"], "code": person["code"], "name": person["name"]},
            "assignments": [present(row) for row in rows],
            "currently_held": len(held),
            "outstanding_value_minor": outstanding,
            "outstanding_value": format_minor(outstanding),
        }

    # -- writes ----------------------------------------------------------------

    async def assign(
        self,
        asset: str,
        employee: str,
        issued_on: str,
        condition: str = "good",
        note: str | None = None,
        actor: str = "mcp",
    ) -> dict:
        require_iso_date(issued_on, "issued_on")
        self._require_condition(condition)
        asset_row = await self._require_asset(asset)
        if asset_row["status"] == "retired":
            raise ValidationError(f"Asset {asset_row['tag']} is retired and cannot be assigned")

        open_assignment = await self._reader.open_assignment(asset_row["id"])
        if open_assignment:
            raise ConflictError(
                f"Asset {asset_row['tag']} · {asset_row['name']} is already held by "
                f"{open_assignment['employee_code']} · {open_assignment['employee_name']} "
                f"since {open_assignment['issued_on']} — return it first"
            )

        person = await self._require_employee(employee)
        if person["status"] == "exited":
            raise ValidationError(
                f"{person['code']} · {person['name']} has exited and cannot be issued assets"
            )

        assignment_id = new_id("asg")
        now = now_iso()
        async with self._db.unit_of_work() as conn:
            await self._writer.insert_assignment(
                conn,
                {
                    "id": assignment_id,
                    "asset_id": asset_row["id"],
                    "employee_id": person["id"],
                    "issued_on": issued_on,
                    "issued_condition": condition,
                    "note": note,
                    "created_at": now,
                },
            )
            await self._writer.set_status(conn, asset_row["id"], "assigned", condition, now)
            await self._audit.append(
                conn,
                {
                    "id": new_id("aud"),
                    "actor": actor,
                    "action": "assign_asset",
                    "object_type": "asset",
                    "object_id": asset_row["id"],
                    "details": f"{asset_row['tag']} · {asset_row['name']} issued to "
                    f"{person['code']} · {person['name']} on {issued_on} ({condition})",
                    "created_at": now_iso(),
                },
            )
        return (await self._reader.get(asset_row["id"])) or {}

    async def return_asset(
        self,
        asset: str,
        returned_on: str,
        condition: str = "good",
        note: str | None = None,
        actor: str = "mcp",
    ) -> dict:
        require_iso_date(returned_on, "returned_on")
        self._require_condition(condition)
        asset_row = await self._require_asset(asset)
        open_assignment = await self._reader.open_assignment(asset_row["id"])
        if not open_assignment:
            raise ConflictError(
                f"Asset {asset_row['tag']} · {asset_row['name']} is not currently assigned"
            )
        if returned_on < open_assignment["issued_on"]:
            raise ValidationError(
                f"returned_on {returned_on} is before it was issued "
                f"({open_assignment['issued_on']})"
            )

        # Damaged kit goes to repair, not back on the shelf.
        new_status = "in_repair" if condition in REPAIR_CONDITIONS else "in_stock"
        now = now_iso()
        async with self._db.unit_of_work() as conn:
            await self._writer.close_assignment(
                conn, open_assignment["id"], returned_on, condition, note
            )
            await self._writer.set_status(conn, asset_row["id"], new_status, condition, now)
            await self._audit.append(
                conn,
                {
                    "id": new_id("aud"),
                    "actor": actor,
                    "action": "return_asset",
                    "object_type": "asset",
                    "object_id": asset_row["id"],
                    "details": f"{asset_row['tag']} · {asset_row['name']} returned by "
                    f"{open_assignment['employee_code']} on {returned_on} "
                    f"({condition} → {new_status})",
                    "created_at": now_iso(),
                },
            )
        return (await self._reader.get(asset_row["id"])) or {}
