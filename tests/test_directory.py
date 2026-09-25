"""Tests for the employment lifecycle and the directory."""

import pytest

from src.container import container
from src.domain.errors import ConflictError, NotFoundError, ValidationError

employees = container.employees
leave = container.leave


async def test_directory_is_seeded():
    rows = await employees.list_employees(include_exited=True)
    assert len(rows) == 9
    codes = {row["code"] for row in rows}
    assert {"PH-1001", "PH-1042", "PH-1203", "PH-1266"} <= codes


async def test_employee_resolves_by_code_email_and_name():
    by_code = await employees.get_employee("PH-1042")
    by_email = await employees.get_employee("aarav@openhr.com")
    by_name = await employees.get_employee("Aarav Kapoor")
    assert by_code["id"] == by_email["id"] == by_name["id"]


async def test_employee_carries_manager_and_reports():
    aarav = await employees.get_employee("PH-1042")
    assert aarav["manager"]["code"] == "PH-1003"
    assert {r["code"] for r in aarav["direct_reports"]} == {"PH-1088", "PH-1203"}


async def test_org_chart_has_a_single_root():
    chart = await employees.org_chart()
    assert len(chart["roots"]) == 1
    assert chart["roots"][0]["code"] == "PH-1001"
    assert chart["roots"][0]["reports"]


async def test_ctc_is_formatted_from_integer_paise():
    rohan = await employees.get_employee("PH-1003")
    assert rohan["ctc_minor"] == 680_000_000
    assert rohan["ctc_lpa"] == "₹68.0 LPA"
    assert rohan["ctc"] == "₹6,800,000.00"


async def test_create_employee_grants_leave_entitlements():
    created = await employees.create(
        code="PH-9001",
        name="Test Joiner",
        email="test.joiner@openhr.com",
        department="Engineering",
        designation="Backend Engineer I",
        joined_on="2026-09-01",
        manager="PH-1042",
        location="Pune",
        band="IC1",
        ctc_minor=120_000_000,
    )
    assert created["status"] == "probation"
    balance = await leave.balance("PH-9001", 2026)
    earned = next(b for b in balance["balances"] if b["leave_type"] == "earned")
    assert earned["entitled_units"] == 36  # 18 days
    assert earned["available_units"] == 36


async def test_duplicate_code_is_rejected():
    with pytest.raises(ConflictError, match="already exists"):
        await employees.create(
            code="PH-1042",
            name="Clone",
            email="clone@openhr.com",
            department="Engineering",
            designation="Engineer",
            joined_on="2026-09-01",
        )


async def test_non_integer_ctc_is_rejected():
    for bad in (True, 12.5, -1):
        with pytest.raises(ValidationError, match="non-negative integer"):
            await employees.create(
                code=f"PH-bad-{bad}",
                name="Bad CTC",
                email=f"bad{bad}@openhr.com",
                department="Engineering",
                designation="Engineer",
                joined_on="2026-09-01",
                ctc_minor=bad,
            )


async def test_unknown_manager_is_rejected():
    with pytest.raises(NotFoundError, match="Manager not found"):
        await employees.create(
            code="PH-9002",
            name="Orphan",
            email="orphan@openhr.com",
            department="Engineering",
            designation="Engineer",
            joined_on="2026-09-01",
            manager="PH-9999",
        )


async def test_status_moves_only_along_the_state_machine():
    confirmed = await employees.update_status("PH-9001", "active", reason="probation cleared")
    assert confirmed["status"] == "active"

    with pytest.raises(ConflictError, match="already"):
        await employees.update_status("PH-9001", "active")

    with pytest.raises(ValidationError, match="Cannot move"):
        await employees.update_status("PH-9001", "probation")


async def test_exiting_requires_a_last_working_day():
    await employees.update_status("PH-9001", "notice", reason="resigned")
    with pytest.raises(ValidationError, match="effective_date"):
        await employees.update_status("PH-9001", "exited")

    exited = await employees.update_status("PH-9001", "exited", effective_date="2026-10-15")
    assert exited["status"] == "exited"
    assert exited["exited_on"] == "2026-10-15"


async def test_exited_is_terminal():
    with pytest.raises(ValidationError, match="terminal"):
        await employees.update_status("PH-9001", "active")


async def test_exited_employees_are_hidden_by_default():
    visible = {row["code"] for row in await employees.list_employees()}
    everyone = {row["code"] for row in await employees.list_employees(include_exited=True)}
    assert "PH-9001" not in visible
    assert "PH-9001" in everyone


async def test_filters_narrow_the_directory():
    engineering = await employees.list_employees(department="Engineering")
    assert {row["code"] for row in engineering} == {"PH-1003", "PH-1042", "PH-1203"}
    reports = await employees.list_employees(manager="PH-1042")
    assert {row["code"] for row in reports} == {"PH-1088", "PH-1203"}
    found = await employees.list_employees(q="Sneha")
    assert len(found) == 1 and found[0]["code"] == "PH-1088"
