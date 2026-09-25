"""Tests for the asset-custody invariants."""

import pytest

from src.container import container
from src.domain.errors import ConflictError, NotFoundError, ValidationError

assets = container.assets


async def test_seeded_assets_and_holders():
    listing = await assets.list_assets()
    assert listing["total"] == 8
    assigned = [a for a in listing["items"] if a["status"] == "assigned"]
    assert len(assigned) == 7
    spare = next(a for a in listing["items"] if a["tag"] == "AST-0008")
    assert spare["status"] == "in_stock" and spare["holder_id"] is None


async def test_value_is_formatted_from_integer_paise():
    listing = await assets.list_assets(q="MacBook Pro")
    laptop = listing["items"][0]
    assert laptop["value_minor"] == 18_900_000
    assert laptop["value"] == "₹189,000.00"


async def test_an_asset_has_one_holder_at_a_time():
    await assets.assign("AST-0008", "PH-1203", "2026-09-20", "good", "spare keyboard")
    with pytest.raises(ConflictError, match="already held by"):
        await assets.assign("AST-0008", "PH-1088", "2026-09-21")
    # Return it and the next assignment is fine.
    await assets.return_asset("AST-0008", "2026-09-25", "good")
    await assets.assign("AST-0008", "PH-1088", "2026-09-26")
    await assets.return_asset("AST-0008", "2026-09-27", "good")


async def test_custody_history_is_append_only():
    history = await assets.employee_assets("PH-1203", include_returned=True)
    keyboard = [row for row in history["assignments"] if row["tag"] == "AST-0008"]
    assert keyboard, "the returned assignment must still be on record"
    assert keyboard[0]["returned_on"] == "2026-09-25"

    current = await assets.employee_assets("PH-1203")
    assert {row["tag"] for row in current["assignments"]} == {"AST-0005"}


async def test_damaged_returns_go_to_repair_not_stock():
    await assets.assign("AST-0008", "PH-1240", "2026-10-01")
    returned = await assets.return_asset("AST-0008", "2026-10-05", "damaged", "keys stuck")
    assert returned["status"] == "in_repair"
    assert returned["condition"] == "damaged"
    # Put it back for the other tests.
    await assets.assign("AST-0008", "PH-1240", "2026-10-06")
    await assets.return_asset("AST-0008", "2026-10-07", "good")


async def test_returning_an_unassigned_asset_is_rejected():
    with pytest.raises(ConflictError, match="not currently assigned"):
        await assets.return_asset("AST-0008", "2026-10-08", "good")


async def test_return_before_issue_is_rejected():
    await assets.assign("AST-0008", "PH-1240", "2026-10-10")
    with pytest.raises(ValidationError, match="before it was issued"):
        await assets.return_asset("AST-0008", "2026-10-01", "good")
    await assets.return_asset("AST-0008", "2026-10-11", "good")


async def test_invalid_condition_is_rejected():
    with pytest.raises(ValidationError, match="Invalid condition"):
        await assets.assign("AST-0008", "PH-1240", "2026-10-12", "mint")


async def test_unknown_asset_and_employee_are_rejected():
    with pytest.raises(NotFoundError, match="Asset not found"):
        await assets.assign("AST-9999", "PH-1240", "2026-10-12")
    with pytest.raises(NotFoundError, match="Employee not found"):
        await assets.assign("AST-0008", "PH-9999", "2026-10-12")


async def test_outstanding_value_sums_what_is_held():
    held = await assets.employee_assets("PH-1042")
    assert {row["tag"] for row in held["assignments"]} == {"AST-0001", "AST-0002"}
    assert held["outstanding_value_minor"] == 18_900_000 + 3_450_000
    assert held["currently_held"] == 2
