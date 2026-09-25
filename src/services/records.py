"""Read-only record use cases — employee documents and the holiday calendar.

Both receive only readers, so this service structurally cannot write.
"""

from src.domain.errors import NotFoundError
from src.repositories.protocols import DocumentReader, EmployeeReader, HolidayReader


def _human_size(size_bytes: int) -> str:
    """Render a byte count without float division: KB below a megabyte, else MB."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes // 1024} KB"
    whole, remainder = divmod(size_bytes, 1024 * 1024)
    return f"{whole}.{(remainder * 10) // (1024 * 1024)} MB"


class RecordsService:
    def __init__(
        self, employees: EmployeeReader, documents: DocumentReader, holidays: HolidayReader
    ):
        self._employees = employees
        self._documents = documents
        self._holidays = holidays

    async def documents(self, employee: str, doc_group: str | None = None) -> dict:
        person = await self._employees.get(employee)
        if not person:
            raise NotFoundError(f"Employee not found: {employee}")
        rows = await self._documents.list_for(person["id"], doc_group)
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            grouped.setdefault(row["doc_group"], []).append(
                {**row, "size": _human_size(int(row["size_bytes"]))}
            )
        return {
            "employee": {"id": person["id"], "code": person["code"], "name": person["name"]},
            "total": len(rows),
            "groups": grouped,
        }

    async def holidays(self, year: int | None = None, region: str | None = None) -> dict:
        rows = await self._holidays.list_rows(year, region)
        return {
            "year": year or "all",
            "region": region or "all",
            "total": len(rows),
            "items": rows,
        }
