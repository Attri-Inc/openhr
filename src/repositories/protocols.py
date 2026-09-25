"""Repository contracts (Protocols).

Services depend on these, never on the concrete SQLite classes (Dependency
Inversion). They are split into narrow Reader/Writer roles (Interface
Segregation): the report service receives only readers and *cannot* mutate a
single row.

Write methods take an opaque `conn` (the connection yielded by a Unit of Work),
so the same transaction spans every write in a use case — the mutation and its
audit row commit together or not at all. The connection type is intentionally
`Any` to keep the contract backend-agnostic.
"""

from typing import Any, Protocol

# ---------------------------------------------------------------------------
# Directory
# ---------------------------------------------------------------------------


class EmployeeReader(Protocol):
    async def get(self, identifier: str) -> dict | None: ...
    async def get_by_id(self, employee_id: str) -> dict | None: ...
    async def list_rows(
        self,
        department: str | None,
        status: str | None,
        manager_id: str | None,
        include_exited: bool,
        q: str | None,
    ) -> list[dict]: ...
    async def direct_reports(self, manager_id: str) -> list[dict]: ...
    async def headcount_rows(self, dimension: str, as_of: str | None) -> list[dict]: ...
    async def tenure_rows(self, date_from: str | None, date_to: str | None) -> list[dict]: ...


class EmployeeWriter(Protocol):
    async def insert(self, conn: Any, employee: dict) -> None: ...
    async def set_status(
        self, conn: Any, employee_id: str, status: str, exited_on: str | None, updated_at: str
    ) -> None: ...


# ---------------------------------------------------------------------------
# Leave
# ---------------------------------------------------------------------------


class LeaveReader(Protocol):
    async def get_request(self, request_id: str) -> dict | None: ...
    async def list_requests(
        self,
        employee_id: str | None,
        leave_type: str | None,
        status: str | None,
        date_from: str | None,
        date_to: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict], int]: ...
    async def consumed_units(self, employee_id: str, leave_type: str, year: int) -> int: ...
    async def entitlement_rows(self, employee_id: str, year: int) -> list[dict]: ...
    async def overlapping(
        self, employee_id: str, start_date: str, end_date: str, exclude_id: str | None
    ) -> list[dict]: ...
    async def on_leave_between(self, date_from: str, date_to: str) -> list[dict]: ...
    async def liability_rows(self, year: int) -> list[dict]: ...


class LeaveWriter(Protocol):
    async def insert_request(self, conn: Any, request: dict) -> None: ...
    async def decide_request(
        self,
        conn: Any,
        request_id: str,
        status: str,
        decided_by: str,
        decided_at: str,
        note: str | None,
    ) -> None: ...
    async def cancel_request(
        self, conn: Any, request_id: str, cancelled_at: str, reason: str
    ) -> None: ...
    async def upsert_entitlement(self, conn: Any, entitlement: dict) -> None: ...


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------


class AssetReader(Protocol):
    async def get(self, identifier: str) -> dict | None: ...
    async def list_rows(
        self, status: str | None, category: str | None, holder_id: str | None, q: str | None
    ) -> list[dict]: ...
    async def open_assignment(self, asset_id: str) -> dict | None: ...
    async def assignments_for(self, employee_id: str, include_returned: bool) -> list[dict]: ...


class AssetWriter(Protocol):
    async def insert_assignment(self, conn: Any, assignment: dict) -> None: ...
    async def close_assignment(
        self, conn: Any, assignment_id: str, returned_on: str, condition: str, note: str | None
    ) -> None: ...
    async def set_status(
        self, conn: Any, asset_id: str, status: str, condition: str | None, updated_at: str
    ) -> None: ...


# ---------------------------------------------------------------------------
# Recruitment
# ---------------------------------------------------------------------------


class RecruitmentReader(Protocol):
    async def list_requisitions(self, status: str | None, department: str | None) -> list[dict]: ...
    async def get_candidate(self, candidate_id: str) -> dict | None: ...
    async def list_candidates(
        self, requisition_id: str | None, stage: str | None, q: str | None
    ) -> list[dict]: ...
    async def interviews_for(self, candidate_id: str) -> list[dict]: ...
    async def hired_count(self, requisition_id: str) -> int: ...


class RecruitmentWriter(Protocol):
    async def set_candidate_stage(
        self, conn: Any, candidate_id: str, stage: str, notes: str | None, updated_at: str
    ) -> None: ...


# ---------------------------------------------------------------------------
# Exits
# ---------------------------------------------------------------------------


class ExitReader(Protocol):
    async def get(self, exit_id: str) -> dict | None: ...
    async def get_by_employee(self, employee_id: str) -> dict | None: ...
    async def clearance_rows(self, exit_id: str) -> list[dict]: ...
    async def list_rows(self, status: str | None) -> list[dict]: ...


class ExitWriter(Protocol):
    async def insert(self, conn: Any, record: dict) -> None: ...
    async def insert_clearance(self, conn: Any, row: dict) -> None: ...
    async def complete_step(
        self, conn: Any, exit_id: str, step: str, done_by: str, done_at: str, note: str | None
    ) -> None: ...
    async def set_status(self, conn: Any, exit_id: str, status: str, updated_at: str) -> None: ...


# ---------------------------------------------------------------------------
# Records, audit, escape hatch
# ---------------------------------------------------------------------------


class DocumentReader(Protocol):
    async def list_for(self, employee_id: str, doc_group: str | None) -> list[dict]: ...


class HolidayReader(Protocol):
    async def list_rows(self, year: int | None, region: str | None) -> list[dict]: ...


class AuditReader(Protocol):
    async def list(
        self, action: str | None, actor: str | None, limit: int, offset: int
    ) -> tuple[list[dict], int]: ...


class AuditWriter(Protocol):
    async def append(self, conn: Any, entry: dict) -> None: ...


class QueryRunner(Protocol):
    async def select(self, sql: str) -> list[dict]: ...
