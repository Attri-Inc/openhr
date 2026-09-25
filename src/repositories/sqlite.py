"""SQLite implementations of the repository protocols.

These are the only classes that know SQL exists. Normal reads run on the
read/write connection so a caller that just wrote inside a Unit of Work sees its
own change; the `run_query` escape hatch deliberately uses the separate
read-only connection (`PRAGMA query_only=ON`), so the engine itself refuses any
write that slips past the service-level guard.
"""

from typing import Any

import aiosqlite

from src.domain.constants import BALANCE_CONSUMING_STATUSES, HEADCOUNT_DIMENSIONS
from src.domain.errors import ConflictError
from src.infrastructure.database import Database, fetch_all

_CONSUMING = tuple(sorted(BALANCE_CONSUMING_STATUSES))
_CONSUMING_PLACEHOLDERS = ", ".join("?" for _ in _CONSUMING)


class SqliteEmployeeRepository:
    def __init__(self, db: Database):
        self._db = db

    async def get(self, identifier: str) -> dict | None:
        """Resolve by id, payroll code, email or name — in that priority order."""
        conn = await self._db.connection()
        rows = await fetch_all(
            conn,
            "SELECT * FROM employees "
            "WHERE id = ? OR code = ? OR email = ? COLLATE NOCASE OR name = ? COLLATE NOCASE "
            "ORDER BY (id = ?) DESC, (code = ?) DESC, (email = ?) DESC LIMIT 1",
            (identifier,) * 7,
        )
        return dict(rows[0]) if rows else None

    async def get_by_id(self, employee_id: str) -> dict | None:
        conn = await self._db.connection()
        rows = await fetch_all(conn, "SELECT * FROM employees WHERE id = ?", [employee_id])
        return dict(rows[0]) if rows else None

    async def list_rows(
        self,
        department: str | None,
        status: str | None,
        manager_id: str | None,
        include_exited: bool,
        q: str | None,
    ) -> list[dict]:
        conn = await self._db.connection()
        conditions, params = ["1=1"], []
        if department:
            conditions.append("e.department = ? COLLATE NOCASE")
            params.append(department)
        if status:
            conditions.append("e.status = ?")
            params.append(status)
        if manager_id:
            conditions.append("e.manager_id = ?")
            params.append(manager_id)
        if not include_exited:
            conditions.append("e.status != 'exited'")
        if q:
            conditions.append("(e.name LIKE ? OR e.code LIKE ? OR e.email LIKE ?)")
            params.extend([f"%{q}%"] * 3)
        rows = await fetch_all(
            conn,
            f"""
            SELECT e.*, m.name AS manager_name, m.code AS manager_code
            FROM employees e
            LEFT JOIN employees m ON e.manager_id = m.id
            WHERE {" AND ".join(conditions)}
            ORDER BY e.code
            """,
            params,
        )
        return [dict(r) for r in rows]

    async def direct_reports(self, manager_id: str) -> list[dict]:
        conn = await self._db.connection()
        rows = await fetch_all(
            conn,
            "SELECT id, code, name, designation, department, status FROM employees "
            "WHERE manager_id = ? AND status != 'exited' ORDER BY code",
            [manager_id],
        )
        return [dict(r) for r in rows]

    async def headcount_rows(self, dimension: str, as_of: str | None) -> list[dict]:
        if dimension not in HEADCOUNT_DIMENSIONS:
            raise ValueError(f"Unsupported headcount dimension: {dimension}")
        conn = await self._db.connection()
        # "Headcount as of D" = joined on or before D, and not yet exited on D.
        conditions, params = ["1=1"], []
        if as_of:
            conditions.append("joined_on <= ?")
            params.append(as_of)
            conditions.append("(exited_on IS NULL OR exited_on > ?)")
            params.append(as_of)
        else:
            conditions.append("status != 'exited'")
        rows = await fetch_all(
            conn,
            f"""
            SELECT {dimension} AS bucket, COUNT(*) AS headcount,
                   COALESCE(SUM(ctc_minor), 0) AS ctc_minor
            FROM employees
            WHERE {" AND ".join(conditions)}
            GROUP BY {dimension}
            ORDER BY headcount DESC, bucket
            """,
            params,
        )
        return [dict(r) for r in rows]

    async def tenure_rows(self, date_from: str | None, date_to: str | None) -> list[dict]:
        """Every employee with the dates attrition is computed from."""
        conn = await self._db.connection()
        conditions, params = ["1=1"], []
        if date_from:
            conditions.append("(exited_on IS NULL OR exited_on >= ?)")
            params.append(date_from)
        if date_to:
            conditions.append("joined_on <= ?")
            params.append(date_to)
        rows = await fetch_all(
            conn,
            f"SELECT id, code, name, department, status, joined_on, exited_on FROM employees "
            f"WHERE {' AND '.join(conditions)} ORDER BY code",
            params,
        )
        return [dict(r) for r in rows]

    async def insert(self, conn: Any, employee: dict) -> None:
        try:
            await conn.execute(
                "INSERT INTO employees (id, code, name, email, phone, department, designation, "
                "manager_id, location, employment_type, band, status, joined_on, date_of_birth, "
                "ctc_minor, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    employee["id"],
                    employee["code"],
                    employee["name"],
                    employee["email"],
                    employee.get("phone"),
                    employee["department"],
                    employee["designation"],
                    employee.get("manager_id"),
                    employee.get("location"),
                    employee["employment_type"],
                    employee.get("band"),
                    employee["status"],
                    employee["joined_on"],
                    employee.get("date_of_birth"),
                    employee["ctc_minor"],
                    employee["created_at"],
                    employee["updated_at"],
                ),
            )
        except aiosqlite.IntegrityError as e:
            raise ConflictError(f"Employee code or email already exists: {e}") from e

    async def set_status(
        self, conn: Any, employee_id: str, status: str, exited_on: str | None, updated_at: str
    ) -> None:
        await conn.execute(
            "UPDATE employees SET status = ?, exited_on = ?, updated_at = ? WHERE id = ?",
            (status, exited_on, updated_at, employee_id),
        )


class SqliteLeaveRepository:
    def __init__(self, db: Database):
        self._db = db

    async def get_request(self, request_id: str) -> dict | None:
        conn = await self._db.connection()
        rows = await fetch_all(
            conn,
            """
            SELECT r.*, e.name AS employee_name, e.code AS employee_code
            FROM leave_requests r JOIN employees e ON r.employee_id = e.id
            WHERE r.id = ?
            """,
            [request_id],
        )
        return dict(rows[0]) if rows else None

    async def list_requests(
        self,
        employee_id: str | None,
        leave_type: str | None,
        status: str | None,
        date_from: str | None,
        date_to: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict], int]:
        conn = await self._db.connection()
        conditions, params = ["1=1"], []
        if employee_id:
            conditions.append("r.employee_id = ?")
            params.append(employee_id)
        if leave_type:
            conditions.append("r.leave_type = ?")
            params.append(leave_type)
        if status:
            conditions.append("r.status = ?")
            params.append(status)
        # Overlap, not containment: a request counts if any of it falls in the window.
        if date_from:
            conditions.append("r.end_date >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("r.start_date <= ?")
            params.append(date_to)
        where = " AND ".join(conditions)

        count_rows = await fetch_all(
            conn, f"SELECT COUNT(*) AS cnt FROM leave_requests r WHERE {where}", params
        )
        rows = await fetch_all(
            conn,
            f"""
            SELECT r.*, e.name AS employee_name, e.code AS employee_code, e.department
            FROM leave_requests r JOIN employees e ON r.employee_id = e.id
            WHERE {where}
            ORDER BY r.start_date DESC, r.created_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        )
        return [dict(r) for r in rows], int(dict(count_rows[0])["cnt"])

    async def consumed_units(self, employee_id: str, leave_type: str, year: int) -> int:
        """Units held by pending + approved requests — the ones that reserve balance."""
        conn = await self._db.connection()
        rows = await fetch_all(
            conn,
            f"""
            SELECT COALESCE(SUM(units), 0) AS units
            FROM leave_requests
            WHERE employee_id = ? AND leave_type = ?
              AND CAST(substr(start_date, 1, 4) AS INTEGER) = ?
              AND status IN ({_CONSUMING_PLACEHOLDERS})
            """,
            [employee_id, leave_type, year, *_CONSUMING],
        )
        return int(dict(rows[0])["units"])

    async def entitlement_rows(self, employee_id: str, year: int) -> list[dict]:
        conn = await self._db.connection()
        rows = await fetch_all(
            conn,
            "SELECT leave_type, entitled_units FROM leave_entitlements "
            "WHERE employee_id = ? AND year = ? ORDER BY leave_type",
            [employee_id, year],
        )
        return [dict(r) for r in rows]

    async def overlapping(
        self, employee_id: str, start_date: str, end_date: str, exclude_id: str | None
    ) -> list[dict]:
        """Live requests whose dates collide with the proposed range."""
        conn = await self._db.connection()
        params: list[Any] = [employee_id, end_date, start_date, *_CONSUMING]
        exclude_clause = ""
        if exclude_id:
            exclude_clause = "AND id != ?"
            params.append(exclude_id)
        rows = await fetch_all(
            conn,
            f"""
            SELECT id, leave_type, start_date, end_date, status
            FROM leave_requests
            WHERE employee_id = ? AND start_date <= ? AND end_date >= ?
              AND status IN ({_CONSUMING_PLACEHOLDERS}) {exclude_clause}
            ORDER BY start_date
            """,
            params,
        )
        return [dict(r) for r in rows]

    async def on_leave_between(self, date_from: str, date_to: str) -> list[dict]:
        conn = await self._db.connection()
        rows = await fetch_all(
            conn,
            """
            SELECT r.id, r.leave_type, r.start_date, r.end_date, r.units, r.reason,
                   e.id AS employee_id, e.code AS employee_code, e.name AS employee_name,
                   e.department, e.location
            FROM leave_requests r JOIN employees e ON r.employee_id = e.id
            WHERE r.status = 'approved' AND r.start_date <= ? AND r.end_date >= ?
            ORDER BY e.department, e.name
            """,
            [date_to, date_from],
        )
        return [dict(r) for r in rows]

    async def liability_rows(self, year: int) -> list[dict]:
        """Entitlement vs consumption per employee and leave type, for the liability report."""
        conn = await self._db.connection()
        rows = await fetch_all(
            conn,
            f"""
            SELECT e.id AS employee_id, e.code, e.name, e.department, e.ctc_minor,
                   en.leave_type, en.entitled_units,
                   COALESCE((
                     SELECT SUM(r.units) FROM leave_requests r
                     WHERE r.employee_id = e.id AND r.leave_type = en.leave_type
                       AND CAST(substr(r.start_date, 1, 4) AS INTEGER) = en.year
                       AND r.status IN ({_CONSUMING_PLACEHOLDERS})
                   ), 0) AS consumed_units
            FROM leave_entitlements en
            JOIN employees e ON en.employee_id = e.id
            WHERE en.year = ? AND e.status != 'exited'
            ORDER BY e.code, en.leave_type
            """,
            [*_CONSUMING, year],
        )
        return [dict(r) for r in rows]

    async def insert_request(self, conn: Any, request: dict) -> None:
        await conn.execute(
            "INSERT INTO leave_requests (id, employee_id, leave_type, start_date, end_date, "
            "units, reason, status, requested_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                request["id"],
                request["employee_id"],
                request["leave_type"],
                request["start_date"],
                request["end_date"],
                request["units"],
                request["reason"],
                request["status"],
                request["requested_by"],
                request["created_at"],
            ),
        )

    async def decide_request(
        self,
        conn: Any,
        request_id: str,
        status: str,
        decided_by: str,
        decided_at: str,
        note: str | None,
    ) -> None:
        await conn.execute(
            "UPDATE leave_requests SET status = ?, decided_by = ?, decided_at = ?, "
            "decision_note = ? WHERE id = ? AND status = 'pending'",
            (status, decided_by, decided_at, note, request_id),
        )

    async def cancel_request(
        self, conn: Any, request_id: str, cancelled_at: str, reason: str
    ) -> None:
        await conn.execute(
            "UPDATE leave_requests SET status = 'cancelled', cancelled_at = ?, cancel_reason = ? "
            "WHERE id = ? AND status IN ('pending', 'approved')",
            (cancelled_at, reason, request_id),
        )

    async def upsert_entitlement(self, conn: Any, entitlement: dict) -> None:
        await conn.execute(
            "INSERT INTO leave_entitlements (id, employee_id, leave_type, year, entitled_units, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (employee_id, leave_type, year) DO UPDATE SET "
            "entitled_units = excluded.entitled_units, updated_at = excluded.updated_at",
            (
                entitlement["id"],
                entitlement["employee_id"],
                entitlement["leave_type"],
                entitlement["year"],
                entitlement["entitled_units"],
                entitlement["created_at"],
                entitlement["updated_at"],
            ),
        )


class SqliteAssetRepository:
    def __init__(self, db: Database):
        self._db = db

    async def get(self, identifier: str) -> dict | None:
        conn = await self._db.connection()
        rows = await fetch_all(
            conn,
            "SELECT * FROM assets WHERE id = ? OR tag = ? OR serial_number = ? OR "
            "name = ? COLLATE NOCASE ORDER BY (id = ?) DESC, (tag = ?) DESC LIMIT 1",
            (identifier,) * 6,
        )
        return dict(rows[0]) if rows else None

    async def list_rows(
        self, status: str | None, category: str | None, holder_id: str | None, q: str | None
    ) -> list[dict]:
        conn = await self._db.connection()
        conditions, params = ["1=1"], []
        if status:
            conditions.append("a.status = ?")
            params.append(status)
        if category:
            conditions.append("a.category = ? COLLATE NOCASE")
            params.append(category)
        if holder_id:
            conditions.append("asg.employee_id = ?")
            params.append(holder_id)
        if q:
            conditions.append("(a.name LIKE ? OR a.tag LIKE ? OR a.serial_number LIKE ?)")
            params.extend([f"%{q}%"] * 3)
        rows = await fetch_all(
            conn,
            f"""
            SELECT a.*, asg.id AS assignment_id, asg.issued_on,
                   h.id AS holder_id, h.code AS holder_code, h.name AS holder_name
            FROM assets a
            LEFT JOIN asset_assignments asg
                   ON asg.asset_id = a.id AND asg.returned_on IS NULL
            LEFT JOIN employees h ON asg.employee_id = h.id
            WHERE {" AND ".join(conditions)}
            ORDER BY a.category, a.tag
            """,
            params,
        )
        return [dict(r) for r in rows]

    async def open_assignment(self, asset_id: str) -> dict | None:
        conn = await self._db.connection()
        rows = await fetch_all(
            conn,
            """
            SELECT asg.*, e.name AS employee_name, e.code AS employee_code
            FROM asset_assignments asg JOIN employees e ON asg.employee_id = e.id
            WHERE asg.asset_id = ? AND asg.returned_on IS NULL
            """,
            [asset_id],
        )
        return dict(rows[0]) if rows else None

    async def assignments_for(self, employee_id: str, include_returned: bool) -> list[dict]:
        conn = await self._db.connection()
        clause = "" if include_returned else "AND asg.returned_on IS NULL"
        rows = await fetch_all(
            conn,
            f"""
            SELECT asg.*, a.tag, a.name AS asset_name, a.category, a.value_minor
            FROM asset_assignments asg JOIN assets a ON asg.asset_id = a.id
            WHERE asg.employee_id = ? {clause}
            ORDER BY asg.issued_on DESC
            """,
            [employee_id],
        )
        return [dict(r) for r in rows]

    async def insert_assignment(self, conn: Any, assignment: dict) -> None:
        try:
            await conn.execute(
                "INSERT INTO asset_assignments (id, asset_id, employee_id, issued_on, "
                "issued_condition, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    assignment["id"],
                    assignment["asset_id"],
                    assignment["employee_id"],
                    assignment["issued_on"],
                    assignment["issued_condition"],
                    assignment.get("note"),
                    assignment["created_at"],
                ),
            )
        except aiosqlite.IntegrityError as e:
            # The partial unique index on (asset_id) WHERE returned_on IS NULL.
            raise ConflictError(f"Asset already has an open assignment: {e}") from e

    async def close_assignment(
        self, conn: Any, assignment_id: str, returned_on: str, condition: str, note: str | None
    ) -> None:
        await conn.execute(
            "UPDATE asset_assignments SET returned_on = ?, returned_condition = ?, "
            "note = COALESCE(?, note) WHERE id = ? AND returned_on IS NULL",
            (returned_on, condition, note, assignment_id),
        )

    async def set_status(
        self, conn: Any, asset_id: str, status: str, condition: str | None, updated_at: str
    ) -> None:
        await conn.execute(
            "UPDATE assets SET status = ?, condition = COALESCE(?, condition), updated_at = ? "
            "WHERE id = ?",
            (status, condition, updated_at, asset_id),
        )


class SqliteRecruitmentRepository:
    def __init__(self, db: Database):
        self._db = db

    async def list_requisitions(self, status: str | None, department: str | None) -> list[dict]:
        conn = await self._db.connection()
        conditions, params = ["1=1"], []
        if status:
            conditions.append("r.status = ?")
            params.append(status)
        if department:
            conditions.append("r.department = ? COLLATE NOCASE")
            params.append(department)
        rows = await fetch_all(
            conn,
            f"""
            SELECT r.*, m.name AS hiring_manager_name,
                   (SELECT COUNT(*) FROM candidates c WHERE c.requisition_id = r.id) AS candidate_count,
                   (SELECT COUNT(*) FROM candidates c
                     WHERE c.requisition_id = r.id AND c.stage = 'hired') AS hired_count
            FROM requisitions r
            LEFT JOIN employees m ON r.hiring_manager_id = m.id
            WHERE {" AND ".join(conditions)}
            ORDER BY r.id
            """,
            params,
        )
        return [dict(r) for r in rows]

    async def get_candidate(self, candidate_id: str) -> dict | None:
        conn = await self._db.connection()
        rows = await fetch_all(
            conn,
            """
            SELECT c.*, r.title AS requisition_title, r.department, r.status AS requisition_status,
                   r.positions
            FROM candidates c JOIN requisitions r ON c.requisition_id = r.id
            WHERE c.id = ?
            """,
            [candidate_id],
        )
        return dict(rows[0]) if rows else None

    async def list_candidates(
        self, requisition_id: str | None, stage: str | None, q: str | None
    ) -> list[dict]:
        conn = await self._db.connection()
        conditions, params = ["1=1"], []
        if requisition_id:
            conditions.append("c.requisition_id = ?")
            params.append(requisition_id)
        if stage:
            conditions.append("c.stage = ?")
            params.append(stage)
        if q:
            conditions.append("(c.name LIKE ? OR c.email LIKE ? OR c.notes LIKE ?)")
            params.extend([f"%{q}%"] * 3)
        rows = await fetch_all(
            conn,
            f"""
            SELECT c.*, r.title AS requisition_title, r.department,
                   (SELECT COUNT(*) FROM interviews i WHERE i.candidate_id = c.id) AS interview_count
            FROM candidates c JOIN requisitions r ON c.requisition_id = r.id
            WHERE {" AND ".join(conditions)}
            ORDER BY c.requisition_id, c.name
            """,
            params,
        )
        return [dict(r) for r in rows]

    async def interviews_for(self, candidate_id: str) -> list[dict]:
        conn = await self._db.connection()
        rows = await fetch_all(
            conn,
            "SELECT * FROM interviews WHERE candidate_id = ? ORDER BY round_no",
            [candidate_id],
        )
        return [dict(r) for r in rows]

    async def hired_count(self, requisition_id: str) -> int:
        conn = await self._db.connection()
        rows = await fetch_all(
            conn,
            "SELECT COUNT(*) AS cnt FROM candidates WHERE requisition_id = ? AND stage = 'hired'",
            [requisition_id],
        )
        return int(dict(rows[0])["cnt"])

    async def set_candidate_stage(
        self, conn: Any, candidate_id: str, stage: str, notes: str | None, updated_at: str
    ) -> None:
        await conn.execute(
            "UPDATE candidates SET stage = ?, notes = COALESCE(?, notes), updated_at = ? "
            "WHERE id = ?",
            (stage, notes, updated_at, candidate_id),
        )


class SqliteExitRepository:
    def __init__(self, db: Database):
        self._db = db

    async def get(self, exit_id: str) -> dict | None:
        conn = await self._db.connection()
        rows = await fetch_all(
            conn,
            """
            SELECT x.*, e.code AS employee_code, e.name AS employee_name, e.department,
                   e.designation
            FROM exits x JOIN employees e ON x.employee_id = e.id WHERE x.id = ?
            """,
            [exit_id],
        )
        return dict(rows[0]) if rows else None

    async def get_by_employee(self, employee_id: str) -> dict | None:
        conn = await self._db.connection()
        rows = await fetch_all(
            conn,
            """
            SELECT x.*, e.code AS employee_code, e.name AS employee_name, e.department,
                   e.designation
            FROM exits x JOIN employees e ON x.employee_id = e.id WHERE x.employee_id = ?
            """,
            [employee_id],
        )
        return dict(rows[0]) if rows else None

    async def clearance_rows(self, exit_id: str) -> list[dict]:
        conn = await self._db.connection()
        rows = await fetch_all(
            conn, "SELECT * FROM exit_clearance WHERE exit_id = ? ORDER BY id", [exit_id]
        )
        return [dict(r) for r in rows]

    async def list_rows(self, status: str | None) -> list[dict]:
        conn = await self._db.connection()
        conditions, params = ["1=1"], []
        if status:
            conditions.append("x.status = ?")
            params.append(status)
        rows = await fetch_all(
            conn,
            f"""
            SELECT x.*, e.code AS employee_code, e.name AS employee_name, e.department
            FROM exits x JOIN employees e ON x.employee_id = e.id
            WHERE {" AND ".join(conditions)}
            ORDER BY x.last_working_day
            """,
            params,
        )
        return [dict(r) for r in rows]

    async def insert(self, conn: Any, record: dict) -> None:
        try:
            await conn.execute(
                "INSERT INTO exits (id, employee_id, reason, resigned_on, last_working_day, "
                "status, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["id"],
                    record["employee_id"],
                    record["reason"],
                    record["resigned_on"],
                    record["last_working_day"],
                    record["status"],
                    record.get("notes"),
                    record["created_at"],
                    record["updated_at"],
                ),
            )
        except aiosqlite.IntegrityError as e:
            raise ConflictError(f"An exit already exists for this employee: {e}") from e

    async def insert_clearance(self, conn: Any, row: dict) -> None:
        await conn.execute(
            "INSERT INTO exit_clearance (id, exit_id, step) VALUES (?, ?, ?)",
            (row["id"], row["exit_id"], row["step"]),
        )

    async def complete_step(
        self, conn: Any, exit_id: str, step: str, done_by: str, done_at: str, note: str | None
    ) -> None:
        await conn.execute(
            "UPDATE exit_clearance SET is_done = 1, done_by = ?, done_at = ?, note = ? "
            "WHERE exit_id = ? AND step = ? AND is_done = 0",
            (done_by, done_at, note, exit_id, step),
        )

    async def set_status(self, conn: Any, exit_id: str, status: str, updated_at: str) -> None:
        await conn.execute(
            "UPDATE exits SET status = ?, updated_at = ? WHERE id = ?",
            (status, updated_at, exit_id),
        )


class SqliteDocumentRepository:
    def __init__(self, db: Database):
        self._db = db

    async def list_for(self, employee_id: str, doc_group: str | None) -> list[dict]:
        conn = await self._db.connection()
        conditions, params = ["employee_id = ?"], [employee_id]
        if doc_group:
            conditions.append("doc_group = ? COLLATE NOCASE")
            params.append(doc_group)
        rows = await fetch_all(
            conn,
            f"SELECT * FROM documents WHERE {' AND '.join(conditions)} "
            f"ORDER BY doc_group, uploaded_at DESC",
            params,
        )
        return [dict(r) for r in rows]


class SqliteHolidayRepository:
    def __init__(self, db: Database):
        self._db = db

    async def list_rows(self, year: int | None, region: str | None) -> list[dict]:
        conn = await self._db.connection()
        conditions: list[str] = ["1=1"]
        params: list[Any] = []
        if year:
            conditions.append("CAST(substr(holiday_date, 1, 4) AS INTEGER) = ?")
            params.append(year)
        if region:
            conditions.append("region = ?")
            params.append(region)
        rows = await fetch_all(
            conn,
            f"SELECT * FROM holidays WHERE {' AND '.join(conditions)} ORDER BY holiday_date",
            params,
        )
        return [dict(r) for r in rows]


class SqliteAuditRepository:
    def __init__(self, db: Database):
        self._db = db

    async def list(
        self, action: str | None, actor: str | None, limit: int, offset: int
    ) -> tuple[list[dict], int]:
        conn = await self._db.connection()
        conditions, params = ["1=1"], []
        if action:
            conditions.append("action = ?")
            params.append(action)
        if actor:
            conditions.append("actor = ?")
            params.append(actor)
        where = " AND ".join(conditions)
        count_rows = await fetch_all(
            conn, f"SELECT COUNT(*) AS cnt FROM audit_log WHERE {where}", params
        )
        rows = await fetch_all(
            conn,
            f"SELECT * FROM audit_log WHERE {where} ORDER BY seq DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        )
        return [dict(r) for r in rows], int(dict(count_rows[0])["cnt"])

    async def append(self, conn: Any, entry: dict) -> None:
        await conn.execute(
            "INSERT INTO audit_log (id, actor, action, object_type, object_id, details, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                entry["id"],
                entry["actor"],
                entry["action"],
                entry["object_type"],
                entry.get("object_id"),
                entry["details"],
                entry["created_at"],
            ),
        )


class SqliteQueryRepository:
    """The escape hatch runs on the engine-enforced read-only connection."""

    def __init__(self, db: Database):
        self._db = db

    async def select(self, sql: str) -> list[dict]:
        conn = await self._db.readonly()
        rows = await fetch_all(conn, sql)
        return [dict(r) for r in rows[:500]]
