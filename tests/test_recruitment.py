"""Tests for the hiring-funnel invariants."""

import pytest

from src.container import container
from src.domain.errors import ConflictError, NotFoundError, ValidationError

recruitment = container.recruitment


async def test_seeded_requisitions_and_open_positions():
    listing = await recruitment.list_requisitions()
    assert listing["total"] == 3
    # 2 + 1 + 1 positions, none filled yet.
    assert listing["open_positions"] == 4


async def test_candidates_carry_their_requisition():
    listing = await recruitment.list_candidates(requisition="MRF-2026-014")
    assert {c["name"] for c in listing["items"]} == {"Ishaan Verma", "Nikita Rao", "Vikram Patel"}


async def test_interview_scores_are_integer_tenths():
    candidate = await recruitment.get_candidate("cnd_0001")
    assert len(candidate["interviews"]) == 3
    assert candidate["interviews"][0]["score_tenths"] == 41
    assert candidate["interviews"][0]["score"] == "4.1 / 5"
    assert candidate["average_score"] == "4.1 / 5"


async def test_an_unscored_interview_has_no_score():
    candidate = await recruitment.get_candidate("cnd_0006")
    assert candidate["interviews"][0]["score"] is None
    assert candidate["average_score"] is None


async def test_a_candidate_advances_one_stage_at_a_time():
    candidate = await recruitment.get_candidate("cnd_0005")
    assert candidate["stage"] == "applied"
    assert candidate["next_stage"] == "screening"

    with pytest.raises(ValidationError, match="one stage at a time"):
        await recruitment.advance("cnd_0005", "offer")

    moved = await recruitment.advance("cnd_0005", "screening", note="phone screen booked")
    assert moved["stage"] == "screening"


async def test_a_candidate_never_moves_backwards():
    with pytest.raises(ValidationError, match="one stage at a time"):
        await recruitment.advance("cnd_0005", "applied")


async def test_terminal_outcomes_are_reachable_and_final():
    rejected = await recruitment.advance("cnd_0004", "rejected", note="agency fee not approved")
    assert rejected["stage"] == "rejected"
    with pytest.raises(ConflictError, match="terminal stage"):
        await recruitment.advance("cnd_0004", "withdrawn")


async def test_hiring_needs_an_approved_requisition():
    # Aditya is on MRF-2026-015, which is still 'pending'.
    await recruitment.advance("cnd_0003", "final_round")
    await recruitment.advance("cnd_0003", "offer")
    with pytest.raises(ValidationError, match="only an approved requisition can hire"):
        await recruitment.advance("cnd_0003", "hired")


async def test_a_requisition_cannot_hire_beyond_its_positions():
    # MRF-2026-014 is approved with 2 positions.
    assert (await recruitment.advance("cnd_0001", "hired"))["stage"] == "hired"

    await recruitment.advance("cnd_0002", "offer")
    assert (await recruitment.advance("cnd_0002", "hired"))["stage"] == "hired"

    listing = await recruitment.list_requisitions(status="approved")
    requisition = listing["items"][0]
    assert requisition["hired_count"] == 2
    assert requisition["open_positions"] == 0

    # Vikram walks the rest of the funnel but the requisition is full.
    for stage in ("manager_round", "final_round", "offer"):
        await recruitment.advance("cnd_0005", stage)
    with pytest.raises(ConflictError, match="is full"):
        await recruitment.advance("cnd_0005", "hired")


async def test_unknown_stage_and_candidate_are_rejected():
    with pytest.raises(ValidationError, match="Unknown stage"):
        await recruitment.advance("cnd_0006", "interviewing")
    with pytest.raises(NotFoundError, match="Candidate not found"):
        await recruitment.advance("cnd_9999", "screening")
