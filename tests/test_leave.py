"""Tests for the leave-balance invariants, run through the service layer."""

import pytest

from src.container import container
from src.days import format_units
from src.domain.errors import ConflictError, NotFoundError, ValidationError

leave = container.leave
employees = container.employees

YEAR = 2026


async def available(employee: str, leave_type: str) -> int:
    balance = await leave.balance(employee, YEAR)
    entry = next(b for b in balance["balances"] if b["leave_type"] == leave_type)
    return entry["available_units"]


async def test_seeded_balances_are_entitlement_minus_reservations():
    # Dev has one approved casual day out of a 12-day quota.
    assert await available("PH-1203", "casual") == 22
    # ...and one pending comp-off day out of the 2 credited to him.
    assert await available("PH-1203", "comp") == 2


async def test_pending_requests_reserve_balance():
    """A request consumes the moment it is raised, not when it is approved."""
    before = await available("PH-1240", "earned")
    request = await leave.request(
        "PH-1240", "earned", "2026-12-01", "2026-12-02", 2, "test reservation"
    )
    assert request["status"] == "pending"
    assert await available("PH-1240", "earned") == before - 4

    # Approving moves no balance — the reservation was already made.
    await leave.decide(request["id"], "approve", "PH-1015")
    assert await available("PH-1240", "earned") == before - 4

    # Cancelling releases it.
    await leave.cancel(request["id"], "test cleanup")
    assert await available("PH-1240", "earned") == before


async def test_tracked_leave_cannot_be_overdrawn():
    have = await available("PH-1203", "earned")
    with pytest.raises(ValidationError, match="Insufficient"):
        await leave.request(
            "PH-1203", "earned", "2026-11-01", "2026-11-30", have // 2 + 1, "too much"
        )


async def test_untracked_leave_is_not_rationed():
    """Work from home is recorded but never blocked on balance."""
    balance = await leave.balance("PH-1203", YEAR)
    wfh = next(b for b in balance["balances"] if b["leave_type"] == "wfh")
    assert wfh["tracked"] is False
    assert wfh["available"] == "not rationed"
    request = await leave.request(
        "PH-1203", "wfh", "2026-11-03", "2026-11-07", 5, "no entitlement needed"
    )
    assert request["status"] == "pending"
    await leave.cancel(request["id"], "test cleanup")


async def test_overlapping_requests_are_rejected():
    with pytest.raises(ConflictError, match="Overlaps"):
        await leave.request(
            "PH-1203", "casual", "2026-09-15", "2026-09-15", 1, "already off that day"
        )


async def test_half_days_are_exact_and_finer_grains_rejected():
    request = await leave.request(
        "PH-1240", "casual", "2026-12-15", "2026-12-15", 0.5, "half day test"
    )
    assert request["units"] == 1
    assert request["days"] == "0.5 days"
    await leave.cancel(request["id"], "test cleanup")

    with pytest.raises(ValidationError, match="whole or half"):
        await leave.request("PH-1240", "casual", "2026-12-16", "2026-12-16", 0.25, "quarter day")


async def test_days_cannot_exceed_the_date_span():
    with pytest.raises(ValidationError, match="spans only"):
        await leave.request("PH-1240", "casual", "2026-12-20", "2026-12-20", 3, "impossible")


async def test_end_before_start_is_rejected():
    with pytest.raises(ValidationError, match="before start_date"):
        await leave.request("PH-1240", "casual", "2026-12-20", "2026-12-18", 1, "backwards")


async def test_reason_is_required():
    with pytest.raises(ValidationError, match="reason is required"):
        await leave.request("PH-1240", "casual", "2026-12-21", "2026-12-21", 1, "   ")


async def test_nobody_decides_their_own_leave():
    pending = await leave.list_requests(employee="PH-1266", status="pending")
    request_id = pending["items"][0]["id"]
    with pytest.raises(ValidationError, match="own leave request"):
        await leave.decide(request_id, "approve", "PH-1266")


async def test_a_decided_request_cannot_be_decided_again():
    request = await leave.request(
        "PH-1240", "casual", "2026-12-22", "2026-12-22", 1, "decide twice test"
    )
    await leave.decide(request["id"], "decline", "PH-1015", note="not now")
    with pytest.raises(ConflictError, match="cannot be"):
        await leave.decide(request["id"], "approve", "PH-1015")
    # A declined request released its balance and cannot be cancelled either.
    with pytest.raises(ConflictError, match="cannot be cancelled"):
        await leave.cancel(request["id"], "too late")


async def test_declining_releases_the_reservation():
    before = await available("PH-1240", "sick")
    request = await leave.request("PH-1240", "sick", "2026-12-28", "2026-12-29", 2, "decline test")
    assert await available("PH-1240", "sick") == before - 4
    await leave.decide(request["id"], "decline", "PH-1015", note="no certificate")
    assert await available("PH-1240", "sick") == before


async def test_entitlement_cannot_be_set_below_what_is_already_used():
    with pytest.raises(ConflictError, match="already used or reserved"):
        await leave.grant_entitlement("PH-1203", "comp", YEAR, 0)


async def test_granting_comp_off_raises_the_balance():
    before = await available("PH-1088", "comp")
    await leave.grant_entitlement("PH-1088", "comp", YEAR, 3)
    assert await available("PH-1088", "comp") == before + 4  # 1 day -> 3 days
    await leave.grant_entitlement("PH-1088", "comp", YEAR, 1)  # restore


async def test_untracked_types_have_no_entitlement_to_grant():
    with pytest.raises(ValidationError, match="not a tracked leave type"):
        await leave.grant_entitlement("PH-1088", "wfh", YEAR, 5)


async def test_unknown_leave_type_is_rejected():
    with pytest.raises(ValidationError, match="Unknown leave_type"):
        await leave.request("PH-1240", "sabbatical", "2026-12-01", "2026-12-01", 1, "nope")


async def test_unknown_employee_is_rejected():
    with pytest.raises(NotFoundError, match="Employee not found"):
        await leave.request("PH-9999", "casual", "2026-12-01", "2026-12-01", 1, "ghost")


async def test_leave_calendar_reports_who_is_out():
    calendar = await leave.calendar("2026-09-15")
    names = {entry["employee_code"] for entry in calendar["entries"]}
    assert {"PH-1088", "PH-1203", "PH-1240"} <= names
    assert calendar["on_leave_count"] == len(calendar["entries"])


async def test_format_units_is_exact():
    assert format_units(0) == "0 days"
    assert format_units(1) == "0.5 days"
    assert format_units(2) == "1 day"
    assert format_units(5) == "2.5 days"
    assert format_units(-3) == "-1.5 days"
