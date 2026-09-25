"""Tests for the report strategies.

These run last (alphabetically) and therefore see the rows the other modules
created, so they assert relationships and a few deterministic values rather than
whole-company totals that earlier tests legitimately move.
"""

import pytest

from src.container import container
from src.domain.errors import ValidationError
from src.services.reports import format_bp

reports = container.reports
employees = container.employees


async def test_headcount_buckets_sum_to_the_total():
    report = await reports.headcount("department")
    assert report["total_headcount"] == sum(b["headcount"] for b in report["buckets"])
    active = await employees.list_employees()
    assert report["total_headcount"] == len(active)


async def test_headcount_shares_are_basis_points():
    report = await reports.headcount("department")
    assert sum(b["share_bp"] for b in report["buckets"]) == pytest.approx(
        10_000, abs=len(report["buckets"])
    )
    engineering = next(b for b in report["buckets"] if b["bucket"] == "Engineering")
    assert engineering["headcount"] == 3
    assert engineering["share"].endswith("%")


async def test_headcount_excludes_exited_people():
    report = await reports.headcount("status")
    assert "exited" not in {b["bucket"] for b in report["buckets"]}


async def test_headcount_as_of_is_historical():
    early = await reports.headcount("department", as_of="2021-06-01")
    latest = await reports.headcount("department")
    assert early["total_headcount"] < latest["total_headcount"]


async def test_headcount_dimension_is_allowlisted():
    with pytest.raises(ValidationError, match="Cannot group headcount by"):
        await reports.headcount("ctc_minor; DROP TABLE employees")


async def test_attrition_over_a_quiet_window_is_zero():
    report = await reports.attrition("2026-01-01", "2026-06-30")
    assert report["opening_headcount"] == report["closing_headcount"] == 9
    assert report["leavers"] == 0
    assert report["joiners"] == 0
    assert report["attrition_rate"] == "0.00%"


async def test_attrition_counts_the_leavers_in_the_window():
    report = await reports.attrition("2026-07-01", "2026-12-31")
    codes = {row["code"] for row in report["leaver_details"]}
    # Both test-created employees exited inside this window.
    assert {"PH-9001", "PH-9101"} <= codes
    assert report["leavers"] == len(report["leaver_details"])
    assert sum(report["leavers_by_department"].values()) == report["leavers"]
    assert report["attrition_rate_bp"] > 0


async def test_leave_liability_values_unused_earned_leave():
    report = await reports.leave_liability(2026)
    priya = next(e for e in report["employees"] if e["code"] == "PH-1001")
    # Full 18-day earned quota untouched, at a ₹55 LPA day rate over 260 days.
    assert priya["unused_units"] == 36
    assert priya["unused"] == "18 days"
    assert priya["liability_minor"] == 38_076_912
    assert priya["liability"] == "₹380,769.12"


async def test_leave_liability_totals_match_the_rows():
    report = await reports.leave_liability(2026)
    assert report["total_liability_minor"] == sum(e["liability_minor"] for e in report["employees"])
    assert report["total_unused_units"] == sum(e["unused_units"] for e in report["employees"])
    assert report["encashable_types"] == ["earned"]


async def test_format_bp_is_exact():
    assert format_bp(0) == "0.00%"
    assert format_bp(1250) == "12.50%"
    assert format_bp(10_000) == "100.00%"
    assert format_bp(-505) == "-5.05%"
