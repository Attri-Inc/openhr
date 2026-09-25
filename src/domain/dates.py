"""Pure date helpers — no I/O.

Every date crossing the tool boundary is an ISO `YYYY-MM-DD` string, validated
here once so no service has to re-implement the check (and no two services can
disagree about what a valid date is).
"""

from datetime import date, datetime

from src.domain.errors import ValidationError


def require_iso_date(value: str, field: str) -> date:
    """Validate an ISO date string and return it as a `date`."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError) as e:
        raise ValidationError(f"{field} must be YYYY-MM-DD, got '{value}'") from e


def require_range(start: str, end: str) -> tuple[date, date]:
    """Validate both ends of a range and that it runs forwards."""
    start_date = require_iso_date(start, "start_date")
    end_date = require_iso_date(end, "end_date")
    if end_date < start_date:
        raise ValidationError(f"end_date {end} is before start_date {start}")
    return start_date, end_date


def calendar_days(start: str, end: str) -> int:
    """Inclusive calendar-day span of a range — the ceiling on how many days may be claimed."""
    start_date, end_date = require_range(start, end)
    return (end_date - start_date).days + 1


def leave_year_of(iso_date: str) -> int:
    """The leave year a date falls in. One deployment, one calendar leave year."""
    return require_iso_date(iso_date, "date").year
