"""Tests for the offboarding invariants."""

import pytest

from src.container import container
from src.domain.constants import EXIT_CLEARANCE_STEPS
from src.domain.errors import ConflictError, NotFoundError, ValidationError

exits = container.exits
employees = container.employees
assets = container.assets


async def test_seeded_exit_matches_the_employment_record():
    karan = await employees.get_employee("PH-1015")
    assert karan["status"] == "notice"
    checklist = await exits.checklist("PH-1015")
    assert checklist["exit"]["status"] == "clearance_pending"
    assert checklist["steps_total"] == len(EXIT_CLEARANCE_STEPS)
    assert checklist["steps_done"] == 1
    assert checklist["ready_to_complete"] is False


async def test_checklist_reads_real_asset_custody():
    checklist = await exits.checklist("PH-1015")
    tags = {asset["tag"] for asset in checklist["assets_outstanding"]}
    assert tags == {"AST-0007"}
    assert checklist["assets_outstanding_value_minor"] == 150_000


async def test_asset_clearance_is_refused_while_kit_is_held():
    with pytest.raises(ConflictError, match="still holds"):
        await exits.complete_step("PH-1015", "assets_returned", "PH-1001")


async def test_initiating_an_exit_puts_the_employee_on_notice():
    await employees.create(
        code="PH-9101",
        name="Exit Tester",
        email="exit.tester@openhr.com",
        department="Marketing",
        designation="Content Lead",
        joined_on="2025-01-06",
        manager="PH-1121",
        status="active",
        ctc_minor=150_000_000,
    )
    checklist = await exits.initiate(
        "PH-9101", "resignation", "2026-09-01", "2026-10-31", notes="test exit"
    )
    assert checklist["exit"]["status"] == "clearance_pending"
    assert checklist["steps_total"] == len(EXIT_CLEARANCE_STEPS)
    assert (await employees.get_employee("PH-9101"))["status"] == "notice"


async def test_one_exit_per_employee():
    with pytest.raises(ConflictError, match="already in progress"):
        await exits.initiate("PH-9101", "resignation", "2026-09-02", "2026-11-01")


async def test_last_working_day_cannot_precede_the_resignation():
    with pytest.raises(ValidationError, match="before resigned_on"):
        await exits.initiate("PH-1266", "resignation", "2026-10-01", "2026-09-01")


async def test_invalid_reason_and_step_are_rejected():
    with pytest.raises(ValidationError, match="Invalid reason"):
        await exits.initiate("PH-1266", "quit", "2026-09-01", "2026-10-01")
    with pytest.raises(ValidationError, match="Unknown clearance step"):
        await exits.complete_step("PH-9101", "laptop_wiped", "PH-1001")


async def test_completing_every_step_exits_the_employee_on_their_last_working_day():
    for step in EXIT_CLEARANCE_STEPS:
        checklist = await exits.complete_step("PH-9101", step, "PH-1001", note=f"{step} ok")
    assert checklist["exit"]["status"] == "completed"
    assert checklist["steps_done"] == len(EXIT_CLEARANCE_STEPS)

    person = await employees.get_employee("PH-9101")
    assert person["status"] == "exited"
    assert person["exited_on"] == "2026-10-31"


async def test_a_step_cannot_be_signed_off_twice():
    with pytest.raises(ConflictError, match="'completed'"):
        await exits.complete_step("PH-9101", "exit_interview", "PH-1001")


async def test_exit_lookup_by_unknown_identifier():
    with pytest.raises(NotFoundError, match="Exit not found"):
        await exits.checklist("PH-9999")
    with pytest.raises(NotFoundError, match="No exit has been initiated"):
        await exits.checklist("PH-1042")


async def test_completed_exit_appears_in_the_list():
    listing = await exits.list_exits(status="completed")
    assert {row["employee_code"] for row in listing["items"]} == {"PH-9101"}
