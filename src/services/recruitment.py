"""Recruitment use cases — requisitions, candidates and the hiring funnel.

The funnel invariant: a candidate moves **forward one stage at a time**, or to a
terminal outcome (rejected / withdrawn). They never move backwards and never skip
a stage, so the stage column alone is an honest record of how far someone got.

A hire additionally cannot exceed the requisition it is against: an approved
requisition for 2 positions can produce at most 2 hires.
"""

from src.domain.constants import (
    ALL_CANDIDATE_STAGES,
    CANDIDATE_OUTCOMES,
    CANDIDATE_STAGES,
    TERMINAL_CANDIDATE_STAGES,
)
from src.domain.errors import ConflictError, NotFoundError, ValidationError
from src.infrastructure.database import Database
from src.infrastructure.identity import new_id, now_iso
from src.money import format_lpa, format_minor
from src.repositories.protocols import AuditWriter, RecruitmentReader, RecruitmentWriter


def format_score(score_tenths: int | None) -> str | None:
    """Render an interview score held as integer tenths, e.g. 45 -> "4.5 / 5"."""
    if score_tenths is None:
        return None
    whole, tenth = divmod(int(score_tenths), 10)
    return f"{whole}.{tenth} / 5"


def present_requisition(row: dict) -> dict:
    low, high = row.get("budget_min_minor"), row.get("budget_max_minor")
    budget = None
    if low is not None and high is not None:
        budget = f"{format_lpa(low)} – {format_lpa(high)}"
    elif low is not None:
        budget = f"from {format_lpa(low)}"
    return {
        **row,
        "budget": budget,
        "open_positions": max(0, int(row.get("positions", 0)) - int(row.get("hired_count", 0))),
    }


def present_candidate(row: dict) -> dict:
    return {
        **row,
        "current_ctc": format_minor(row["current_ctc_minor"])
        if row.get("current_ctc_minor") is not None
        else None,
        "expected_ctc": format_minor(row["expected_ctc_minor"])
        if row.get("expected_ctc_minor") is not None
        else None,
        "expected_ctc_lpa": format_lpa(row["expected_ctc_minor"])
        if row.get("expected_ctc_minor") is not None
        else None,
    }


def next_stage(stage: str) -> str | None:
    """The one stage a live candidate may advance to, or None at the end of the funnel."""
    if stage not in CANDIDATE_STAGES:
        return None
    index = CANDIDATE_STAGES.index(stage)
    return CANDIDATE_STAGES[index + 1] if index + 1 < len(CANDIDATE_STAGES) else None


class RecruitmentService:
    def __init__(
        self,
        db: Database,
        reader: RecruitmentReader,
        writer: RecruitmentWriter,
        audit: AuditWriter,
    ):
        self._db = db
        self._reader = reader
        self._writer = writer
        self._audit = audit

    # -- reads -----------------------------------------------------------------

    async def list_requisitions(
        self, status: str | None = None, department: str | None = None
    ) -> dict:
        rows = await self._reader.list_requisitions(status, department)
        items = [present_requisition(row) for row in rows]
        return {
            "items": items,
            "total": len(items),
            "open_positions": sum(item["open_positions"] for item in items),
        }

    async def list_candidates(
        self, requisition: str | None = None, stage: str | None = None, q: str | None = None
    ) -> dict:
        if stage and stage not in ALL_CANDIDATE_STAGES:
            raise ValidationError(
                f"Unknown stage '{stage}'. Must be one of: {', '.join(sorted(ALL_CANDIDATE_STAGES))}"
            )
        rows = await self._reader.list_candidates(requisition, stage, q)
        return {"items": [present_candidate(row) for row in rows], "total": len(rows)}

    async def get_candidate(self, candidate_id: str) -> dict | None:
        row = await self._reader.get_candidate(candidate_id)
        if not row:
            return None
        interviews = await self._reader.interviews_for(candidate_id)
        scored = [i["score_tenths"] for i in interviews if i.get("score_tenths") is not None]
        return {
            **present_candidate(row),
            "interviews": [{**i, "score": format_score(i.get("score_tenths"))} for i in interviews],
            # Integer arithmetic: average of tenths, rounded half-up, stays in tenths.
            "average_score": format_score((sum(scored) * 2 + len(scored)) // (2 * len(scored)))
            if scored
            else None,
            "next_stage": next_stage(row["stage"]),
        }

    # -- writes ----------------------------------------------------------------

    async def advance(
        self, candidate_id: str, to_stage: str, note: str | None = None, actor: str = "mcp"
    ) -> dict:
        if to_stage not in ALL_CANDIDATE_STAGES:
            raise ValidationError(
                f"Unknown stage '{to_stage}'. Must be one of: "
                f"{', '.join(sorted(ALL_CANDIDATE_STAGES))}"
            )
        candidate = await self._reader.get_candidate(candidate_id)
        if not candidate:
            raise NotFoundError(f"Candidate not found: {candidate_id}")
        current = candidate["stage"]
        if current in TERMINAL_CANDIDATE_STAGES:
            raise ConflictError(
                f"{candidate['name']} is already '{current}' — that is a terminal stage"
            )

        allowed = {stage for stage in (next_stage(current),) if stage} | CANDIDATE_OUTCOMES
        if to_stage not in allowed:
            raise ValidationError(
                f"Cannot move {candidate['name']} from '{current}' to '{to_stage}'. "
                f"A candidate advances one stage at a time: allowed here is "
                f"{', '.join(sorted(allowed))}."
            )

        if to_stage == "hired":
            if candidate["requisition_status"] != "approved":
                raise ValidationError(
                    f"Requisition {candidate['requisition_id']} is "
                    f"'{candidate['requisition_status']}' — only an approved requisition can hire"
                )
            hired = await self._reader.hired_count(candidate["requisition_id"])
            if hired >= int(candidate["positions"]):
                raise ConflictError(
                    f"Requisition {candidate['requisition_id']} is full: "
                    f"{hired} of {candidate['positions']} positions already hired"
                )

        now = now_iso()
        async with self._db.unit_of_work() as conn:
            await self._writer.set_candidate_stage(conn, candidate_id, to_stage, note, now)
            await self._audit.append(
                conn,
                {
                    "id": new_id("aud"),
                    "actor": actor,
                    "action": "advance_candidate",
                    "object_type": "candidate",
                    "object_id": candidate_id,
                    "details": f"{candidate['name']} ({candidate['requisition_id']}): "
                    f"{current} → {to_stage}" + (f" — {note}" if note else ""),
                    "created_at": now_iso(),
                },
            )
        return (await self.get_candidate(candidate_id)) or {}
