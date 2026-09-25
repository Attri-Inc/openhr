"""People reports as interchangeable strategies.

Each report is a ReportStrategy. Adding one (e.g. Diversity, Tenure) means adding
a class and a ReportService method — nothing existing changes (Open/Closed).
Reports get only readers, so they *cannot* mutate a single row (Interface
Segregation).

Every number here is computed with integer arithmetic. Rates are carried as
integer **basis points** (10,000 bp = 100%) and only formatted for display, so
two callers can never disagree about a percentage by a rounding step.
"""

from typing import Protocol

from src.days import format_units
from src.domain.constants import HEADCOUNT_DIMENSIONS, LEAVE_POLICY
from src.domain.dates import require_iso_date
from src.domain.errors import ValidationError
from src.money import format_minor
from src.repositories.protocols import EmployeeReader, LeaveReader

# Paid working days in a year — the divisor that turns an annual CTC into a day rate.
WORKING_DAYS_PER_YEAR = 260


def format_bp(basis_points: int) -> str:
    """Render integer basis points as a percentage, e.g. 1250 -> "12.50%"."""
    sign = "-" if basis_points < 0 else ""
    whole, frac = divmod(abs(int(basis_points)), 100)
    return f"{sign}{whole}.{frac:02d}%"


def _rate_bp(numerator: int, denominator: int) -> int:
    """numerator/denominator as basis points, half-up, without float division."""
    if denominator == 0:
        return 0
    return (numerator * 10_000 * 2 + denominator) // (denominator * 2)


class ReportStrategy(Protocol):
    async def generate(self) -> dict: ...


class HeadcountReport:
    """Active headcount, broken down along one dimension."""

    def __init__(
        self, employees: EmployeeReader, dimension: str = "department", as_of: str | None = None
    ):
        self._employees = employees
        self._dimension = dimension
        self._as_of = as_of

    async def generate(self) -> dict:
        if self._dimension not in HEADCOUNT_DIMENSIONS:
            raise ValidationError(
                f"Cannot group headcount by '{self._dimension}'. Must be one of: "
                f"{', '.join(sorted(HEADCOUNT_DIMENSIONS))}"
            )
        if self._as_of:
            require_iso_date(self._as_of, "as_of")
        rows = await self._employees.headcount_rows(self._dimension, self._as_of)
        total = sum(int(row["headcount"]) for row in rows)
        total_ctc = sum(int(row["ctc_minor"]) for row in rows)
        return {
            "dimension": self._dimension,
            "as_of": self._as_of or "latest",
            "total_headcount": total,
            "total_ctc_minor": total_ctc,
            "total_ctc": format_minor(total_ctc),
            "buckets": [
                {
                    "bucket": row["bucket"],
                    "headcount": int(row["headcount"]),
                    "share_bp": _rate_bp(int(row["headcount"]), total),
                    "share": format_bp(_rate_bp(int(row["headcount"]), total)),
                    "ctc_minor": int(row["ctc_minor"]),
                    "ctc": format_minor(int(row["ctc_minor"])),
                }
                for row in rows
            ],
        }


class AttritionReport:
    """Exits over a window, against the average headcount for that window."""

    def __init__(self, employees: EmployeeReader, date_from: str, date_to: str):
        self._employees = employees
        self._from = date_from
        self._to = date_to

    async def generate(self) -> dict:
        require_iso_date(self._from, "date_from")
        require_iso_date(self._to, "date_to")
        rows = await self._employees.tenure_rows(self._from, self._to)

        def headcount_on(day: str) -> int:
            return sum(
                1
                for row in rows
                if row["joined_on"] <= day and (not row["exited_on"] or row["exited_on"] > day)
            )

        opening, closing = headcount_on(self._from), headcount_on(self._to)
        leavers = [
            row for row in rows if row["exited_on"] and self._from <= row["exited_on"] <= self._to
        ]
        joiners = [row for row in rows if self._from <= row["joined_on"] <= self._to]
        # Average headcount, doubled, so the division below stays in integers.
        average_doubled = opening + closing
        rate_bp = (
            (len(leavers) * 10_000 * 2 * 2 + average_doubled) // (average_doubled * 2)
            if average_doubled
            else 0
        )

        by_department: dict[str, int] = {}
        for row in leavers:
            by_department[row["department"]] = by_department.get(row["department"], 0) + 1

        return {
            "period": {"from": self._from, "to": self._to},
            "opening_headcount": opening,
            "closing_headcount": closing,
            "joiners": len(joiners),
            "leavers": len(leavers),
            "attrition_rate_bp": rate_bp,
            "attrition_rate": format_bp(rate_bp),
            "leavers_by_department": by_department,
            "leaver_details": [
                {
                    "code": row["code"],
                    "name": row["name"],
                    "department": row["department"],
                    "joined_on": row["joined_on"],
                    "exited_on": row["exited_on"],
                }
                for row in leavers
            ],
        }


class LeaveLiabilityReport:
    """Unused, encashable leave valued at each employee's day rate.

    Only leave types that are *tracked* carry a balance, and only the accruing
    ones represent a real liability — work-from-home is not money owed.
    """

    def __init__(
        self, leave: LeaveReader, year: int, encashable_types: tuple[str, ...] = ("earned",)
    ):
        self._leave = leave
        self._year = year
        self._encashable = encashable_types

    async def generate(self) -> dict:
        rows = await self._leave.liability_rows(self._year)
        employees: dict[str, dict] = {}
        total_units = 0
        total_liability = 0
        for row in rows:
            unused = int(row["entitled_units"]) - int(row["consumed_units"])
            if unused <= 0 or row["leave_type"] not in self._encashable:
                continue
            day_rate_minor = int(row["ctc_minor"]) // WORKING_DAYS_PER_YEAR
            # units are half-days: value = unused * day_rate / 2, integer-only.
            liability = unused * day_rate_minor // 2
            total_units += unused
            total_liability += liability
            entry = employees.setdefault(
                row["employee_id"],
                {
                    "code": row["code"],
                    "name": row["name"],
                    "department": row["department"],
                    "unused_units": 0,
                    "liability_minor": 0,
                    "types": [],
                },
            )
            entry["unused_units"] += unused
            entry["liability_minor"] += liability
            entry["types"].append(
                {
                    "leave_type": row["leave_type"],
                    "name": LEAVE_POLICY[row["leave_type"]]["name"],
                    "unused_units": unused,
                    "unused": format_units(unused),
                    "liability_minor": liability,
                    "liability": format_minor(liability),
                }
            )

        items = sorted(employees.values(), key=lambda e: -e["liability_minor"])
        for item in items:
            item["unused"] = format_units(item["unused_units"])
            item["liability"] = format_minor(item["liability_minor"])
        return {
            "year": self._year,
            "encashable_types": list(self._encashable),
            "working_days_per_year": WORKING_DAYS_PER_YEAR,
            "employees": items,
            "total_unused_units": total_units,
            "total_unused": format_units(total_units),
            "total_liability_minor": total_liability,
            "total_liability": format_minor(total_liability),
        }


class ReportService:
    def __init__(self, employees: EmployeeReader, leave: LeaveReader):
        self._employees = employees
        self._leave = leave

    async def headcount(self, dimension: str = "department", as_of: str | None = None) -> dict:
        return await HeadcountReport(self._employees, dimension, as_of).generate()

    async def attrition(self, date_from: str, date_to: str) -> dict:
        return await AttritionReport(self._employees, date_from, date_to).generate()

    async def leave_liability(self, year: int) -> dict:
        return await LeaveLiabilityReport(self._leave, year).generate()
