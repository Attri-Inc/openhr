"""Composition root — the only place concrete implementations are chosen and wired.

Everything else depends on protocols. To swap SQLite for Postgres, you implement
the repository protocols and change this file; no service or tool changes.
"""

from src.config import DB_PATH
from src.infrastructure.database import Database
from src.repositories.sqlite import (
    SqliteAssetRepository,
    SqliteAuditRepository,
    SqliteDocumentRepository,
    SqliteEmployeeRepository,
    SqliteExitRepository,
    SqliteHolidayRepository,
    SqliteLeaveRepository,
    SqliteQueryRepository,
    SqliteRecruitmentRepository,
)
from src.services.assets import AssetService
from src.services.audit import AuditService
from src.services.directory import EmployeeService
from src.services.leave import LeaveService
from src.services.offboarding import ExitService
from src.services.query import QueryService
from src.services.records import RecordsService
from src.services.recruitment import RecruitmentService
from src.services.reports import ReportService


class Container:
    def __init__(self, db_path: str = DB_PATH):
        self.database = Database(db_path)

        employees_repo = SqliteEmployeeRepository(self.database)
        leave_repo = SqliteLeaveRepository(self.database)
        assets_repo = SqliteAssetRepository(self.database)
        recruitment_repo = SqliteRecruitmentRepository(self.database)
        exits_repo = SqliteExitRepository(self.database)
        documents_repo = SqliteDocumentRepository(self.database)
        holidays_repo = SqliteHolidayRepository(self.database)
        audit_repo = SqliteAuditRepository(self.database)
        query_repo = SqliteQueryRepository(self.database)

        # Each service is handed the narrowest roles it needs: the report and
        # records services get readers only and cannot mutate anything.
        self.employees = EmployeeService(
            self.database, employees_repo, employees_repo, leave_repo, audit_repo
        )
        self.leave = LeaveService(self.database, employees_repo, leave_repo, leave_repo, audit_repo)
        self.assets = AssetService(
            self.database, employees_repo, assets_repo, assets_repo, audit_repo
        )
        self.recruitment = RecruitmentService(
            self.database, recruitment_repo, recruitment_repo, audit_repo
        )
        self.exits = ExitService(
            self.database,
            employees_repo,
            employees_repo,
            assets_repo,
            leave_repo,
            exits_repo,
            exits_repo,
            audit_repo,
        )
        self.reports = ReportService(employees_repo, leave_repo)
        self.records = RecordsService(employees_repo, documents_repo, holidays_repo)
        self.audit = AuditService(audit_repo)
        self.queries = QueryService(query_repo)

    async def close(self) -> None:
        await self.database.close()


# Process-wide singleton used by the MCP server.
container = Container()
