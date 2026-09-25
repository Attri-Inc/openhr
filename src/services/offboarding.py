"""Offboarding use cases — resignation, clearance and the final exit.

The offboarding invariants:

1. One exit per employee, ever (a UNIQUE column backs it up).
2. Initiating an exit moves the employee to `notice` in the *same* DB
   transaction that creates the exit and its clearance checklist — an exit
   record and an employment status can never disagree.
3. `assets_returned` cannot be ticked while the person still holds company kit.
   The checklist reads the real custody table, not a self-reported flag.
4. An employee becomes `exited` only when every clearance step is done, and the
   exit date is the last working day recorded up front — not the day someone
   happened to click the button.
"""

from src.domain.constants import EXIT_CLEARANCE_STEPS, EXIT_REASONS
from src.domain.dates import require_iso_date
from src.domain.errors import ConflictError, NotFoundError, ValidationError
from src.infrastructure.database import Database
from src.infrastructure.identity import new_id, now_iso
from src.money import format_minor
from src.repositories.protocols import (
    AssetReader,
    AuditWriter,
    EmployeeReader,
    EmployeeWriter,
    ExitReader,
    ExitWriter,
    LeaveReader,
)


class ExitService:
    def __init__(
        self,
        db: Database,
        employees_read: EmployeeReader,
        employees_write: EmployeeWriter,
        assets: AssetReader,
        leave: LeaveReader,
        reader: ExitReader,
        writer: ExitWriter,
        audit: AuditWriter,
    ):
        self._db = db
        self._employees = employees_read
        self._employees_write = employees_write
        self._assets = assets
        self._leave = leave
        self._reader = reader
        self._writer = writer
        self._audit = audit

    async def _require_employee(self, identifier: str) -> dict:
        employee = await self._employees.get(identifier)
        if not employee:
            raise NotFoundError(f"Employee not found: {identifier}")
        return employee

    async def _resolve_exit(self, identifier: str) -> dict:
        """Accept either an exit id or any employee identifier."""
        record = await self._reader.get(identifier)
        if record:
            return record
        employee = await self._employees.get(identifier)
        if employee:
            record = await self._reader.get_by_employee(employee["id"])
            if record:
                return record
            raise NotFoundError(f"No exit has been initiated for {employee['code']}")
        raise NotFoundError(f"Exit not found: {identifier}")

    # -- reads -----------------------------------------------------------------

    async def list_exits(self, status: str | None = None) -> dict:
        rows = await self._reader.list_rows(status)
        return {"items": rows, "total": len(rows)}

    async def checklist(self, identifier: str) -> dict:
        record = await self._resolve_exit(identifier)
        steps = await self._reader.clearance_rows(record["id"])
        held = await self._assets.assignments_for(record["employee_id"], include_returned=False)
        pending_leave, _ = await self._leave.list_requests(
            record["employee_id"], None, "pending", None, None, 50, 0
        )
        outstanding_value = sum(row.get("value_minor") or 0 for row in held)
        done = [step for step in steps if step["is_done"]]
        return {
            "exit": record,
            "clearance": steps,
            "steps_done": len(done),
            "steps_total": len(steps),
            "ready_to_complete": len(done) == len(steps) and record["status"] != "completed",
            "assets_outstanding": [
                {
                    "assignment_id": row["id"],
                    "tag": row["tag"],
                    "name": row["asset_name"],
                    "issued_on": row["issued_on"],
                    "value": format_minor(row.get("value_minor") or 0),
                }
                for row in held
            ],
            "assets_outstanding_value_minor": outstanding_value,
            "assets_outstanding_value": format_minor(outstanding_value),
            "leave_requests_pending": len(pending_leave),
        }

    # -- writes ----------------------------------------------------------------

    async def initiate(
        self,
        employee: str,
        reason: str,
        resigned_on: str,
        last_working_day: str,
        notes: str | None = None,
        actor: str = "mcp",
    ) -> dict:
        if reason not in EXIT_REASONS:
            raise ValidationError(
                f"Invalid reason '{reason}'. Must be one of: {', '.join(sorted(EXIT_REASONS))}"
            )
        require_iso_date(resigned_on, "resigned_on")
        require_iso_date(last_working_day, "last_working_day")
        if last_working_day < resigned_on:
            raise ValidationError(
                f"last_working_day {last_working_day} is before resigned_on {resigned_on}"
            )

        person = await self._require_employee(employee)
        if person["status"] == "exited":
            raise ConflictError(f"{person['code']} · {person['name']} has already exited")
        if await self._reader.get_by_employee(person["id"]):
            raise ConflictError(f"An exit is already in progress for {person['code']}")
        if last_working_day < person["joined_on"]:
            raise ValidationError(
                f"last_working_day {last_working_day} is before the joining date "
                f"{person['joined_on']}"
            )

        exit_id = new_id("exit")
        now = now_iso()
        async with self._db.unit_of_work() as conn:
            await self._writer.insert(
                conn,
                {
                    "id": exit_id,
                    "employee_id": person["id"],
                    "reason": reason,
                    "resigned_on": resigned_on,
                    "last_working_day": last_working_day,
                    "status": "clearance_pending",
                    "notes": notes,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            for step in EXIT_CLEARANCE_STEPS:
                await self._writer.insert_clearance(
                    conn, {"id": new_id("clr"), "exit_id": exit_id, "step": step}
                )
            # The employment record and the exit record move together or not at all.
            if person["status"] != "notice":
                await self._employees_write.set_status(conn, person["id"], "notice", None, now)
            await self._audit.append(
                conn,
                {
                    "id": new_id("aud"),
                    "actor": actor,
                    "action": "initiate_exit",
                    "object_type": "exit",
                    "object_id": exit_id,
                    "details": f"{person['code']} · {person['name']} — {reason}, LWD "
                    f"{last_working_day}",
                    "created_at": now_iso(),
                },
            )
        return await self.checklist(exit_id)

    async def complete_step(
        self,
        identifier: str,
        step: str,
        done_by: str,
        note: str | None = None,
        actor: str = "mcp",
    ) -> dict:
        if step not in EXIT_CLEARANCE_STEPS:
            raise ValidationError(
                f"Unknown clearance step '{step}'. Must be one of: "
                f"{', '.join(EXIT_CLEARANCE_STEPS)}"
            )
        record = await self._resolve_exit(identifier)
        if record["status"] in ("completed", "withdrawn"):
            raise ConflictError(f"Exit {record['id']} is '{record['status']}'")
        steps = {row["step"]: row for row in await self._reader.clearance_rows(record["id"])}
        if steps[step]["is_done"]:
            raise ConflictError(f"Clearance step '{step}' is already done")

        signer = await self._employees.get(done_by)
        if not signer:
            raise NotFoundError(f"Signer not found: {done_by}")

        if step == "assets_returned":
            held = await self._assets.assignments_for(record["employee_id"], include_returned=False)
            if held:
                tags = ", ".join(f"{row['tag']} ({row['asset_name']})" for row in held)
                raise ConflictError(
                    f"{record['employee_code']} still holds {len(held)} asset(s): {tags}. "
                    f"Return them before signing off asset clearance."
                )

        now = now_iso()
        remaining = [name for name, row in steps.items() if not row["is_done"] and name != step]
        async with self._db.unit_of_work() as conn:
            await self._writer.complete_step(conn, record["id"], step, signer["id"], now, note)
            await self._audit.append(
                conn,
                {
                    "id": new_id("aud"),
                    "actor": actor,
                    "action": "complete_exit_step",
                    "object_type": "exit",
                    "object_id": record["id"],
                    "details": f"{record['employee_code']} clearance '{step}' signed off by "
                    f"{signer['code']}" + (f" — {note}" if note else ""),
                    "created_at": now_iso(),
                },
            )
            if not remaining:
                # Last gate closed: the exit completes and the employment record
                # closes on the last working day, in this same transaction.
                await self._writer.set_status(conn, record["id"], "completed", now)
                await self._employees_write.set_status(
                    conn,
                    record["employee_id"],
                    "exited",
                    record["last_working_day"],
                    now,
                )
                await self._audit.append(
                    conn,
                    {
                        "id": new_id("aud"),
                        "actor": actor,
                        "action": "complete_exit",
                        "object_type": "exit",
                        "object_id": record["id"],
                        "details": f"{record['employee_code']} · {record['employee_name']} exited "
                        f"on {record['last_working_day']} — all clearance complete",
                        "created_at": now_iso(),
                    },
                )
        return await self.checklist(record["id"])
