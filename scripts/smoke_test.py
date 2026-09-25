"""Smoke test — exercises every MCP tool against the seeded database.

Calls each tool function through the MCP server’s tool registry, validates the
core invariants (leave cannot be overdrawn, an asset has one holder, a candidate
advances one stage, an exit cannot clear while kit is held), and prints proof.

Usage: .venv/bin/python scripts/smoke_test.py
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.container import container  # noqa: E402
from src.mcp_server import mcp  # noqa: E402

PASS, FAIL = "✓", "✗"
EXPECTED_TOOLS = 31
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {PASS if ok else FAIL} {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(name)


async def call(tool: str, **kwargs: Any) -> Any:
    """Invoke a registered MCP tool by name, exactly as Claude would."""
    result = await mcp.call_tool(tool, kwargs)
    # MCPServer returns a CallToolResult; the first content block is TextContent.
    return json.loads(result.content[0].text)  # type: ignore[union-attr]


def units_of(balance: Any, leave_type: str) -> int:
    return next(b for b in balance["balances"] if b["leave_type"] == leave_type)["available_units"]


async def main() -> None:
    print("1. Tool registry")
    tools = await mcp.list_tools()
    names = sorted(t.name for t in tools)
    check(f"{EXPECTED_TOOLS} tools registered", len(tools) == EXPECTED_TOOLS, ", ".join(names))

    print("2. Directory (read)")
    people = await call("list_employees")
    check("list_employees", len(people) == 9, f"{len(people)} active employees")

    aarav = await call("get_employee", employee="PH-1042")
    check(
        "get_employee (by code)",
        aarav.get("manager", {}).get("code") == "PH-1003",
        f"{aarav['name']} · {aarav['ctc_lpa']} · {aarav['direct_report_count']} reports",
    )

    chart = await call("get_org_chart")
    check(
        "get_org_chart",
        len(chart["roots"]) == 1 and chart["roots"][0]["code"] == "PH-1001",
        f"root {chart['roots'][0]['name']}",
    )

    missing = await call("get_employee", employee="PH-9999")
    check("get_employee (unknown)", "error" in missing, missing.get("error", ""))

    print("3. Leave (read)")
    balance = await call("get_leave_balance", employee="PH-1203", year=2026)
    check(
        "get_leave_balance",
        units_of(balance, "casual") == 22,
        f"Dev casual {next(b for b in balance['balances'] if b['leave_type'] == 'casual')['available']}",
    )

    pending = await call("list_leave_requests", status="pending")
    check("list_leave_requests", pending["total"] == 4, f"{pending['total']} pending")

    calendar = await call("get_leave_calendar", date_from="2026-09-15")
    check(
        "get_leave_calendar",
        calendar["on_leave_count"] == 3,
        f"{calendar['on_leave_count']} out on 15 Sep across "
        f"{len(calendar['by_department'])} departments",
    )

    print("4. Assets, recruitment, exits (read)")
    kit = await call("list_assets")
    check(
        "list_assets",
        kit["total"] == 8,
        f"{kit['total']} assets worth {kit['total_value']}",
    )

    karan_kit = await call("get_employee_assets", employee="PH-1015")
    check(
        "get_employee_assets",
        karan_kit["currently_held"] == 1,
        f"Karan holds {karan_kit['currently_held']} ({karan_kit['outstanding_value']})",
    )

    reqs = await call("list_requisitions")
    check(
        "list_requisitions",
        reqs["total"] == 3 and reqs["open_positions"] == 4,
        f"{reqs['total']} MRFs, {reqs['open_positions']} open positions",
    )

    candidates = await call("list_candidates", stage="offer")
    check("list_candidates", len(candidates["items"]) == 1, "1 candidate at offer")

    ishaan = await call("get_candidate", candidate_id="cnd_0001")
    check(
        "get_candidate",
        len(ishaan["interviews"]) == 3,
        f"{ishaan['name']} · {len(ishaan['interviews'])} rounds · avg {ishaan['average_score']}",
    )

    open_exits = await call("list_exits")
    check("list_exits", open_exits["total"] == 1, f"{open_exits['total']} exit in progress")

    checklist = await call("get_exit_checklist", employee="PH-1015")
    check(
        "get_exit_checklist",
        checklist["steps_done"] == 1 and len(checklist["assets_outstanding"]) == 1,
        f"{checklist['steps_done']}/{checklist['steps_total']} steps, "
        f"{len(checklist['assets_outstanding'])} asset outstanding",
    )

    print("5. Reports (read)")
    headcount = await call("get_headcount_report", dimension="department")
    check(
        "get_headcount_report",
        headcount["total_headcount"] == sum(b["headcount"] for b in headcount["buckets"]),
        f"{headcount['total_headcount']} across {len(headcount['buckets'])} departments",
    )

    attrition = await call("get_attrition_report", date_from="2026-01-01", date_to="2026-06-30")
    check(
        "get_attrition_report",
        attrition["leavers"] == 0 and attrition["attrition_rate"] == "0.00%",
        f"{attrition['leavers']} leavers, rate {attrition['attrition_rate']}",
    )

    liability = await call("get_leave_liability_report", year=2026)
    check(
        "get_leave_liability_report",
        liability["total_liability_minor"]
        == sum(e["liability_minor"] for e in liability["employees"]),
        f"{liability['total_unused']} unused worth {liability['total_liability']}",
    )

    bad_dimension = await call("get_headcount_report", dimension="salary")
    check(
        "headcount dimension allowlisted", "error" in bad_dimension, bad_dimension.get("error", "")
    )

    print("6. Records, audit, query (read)")
    docs = await call("list_employee_documents", employee="PH-1042")
    check(
        "list_employee_documents",
        docs["total"] == 9,
        f"{docs['total']} documents in {len(docs['groups'])} groups",
    )

    holidays = await call("list_holidays", year=2026)
    check("list_holidays", holidays["total"] == 11, f"{holidays['total']} holidays in 2026")

    audit = await call("get_audit_log", limit=5)
    check("get_audit_log", audit["total"] >= 29, f"{audit['total']} audit rows")

    rows = await call("run_query", sql="SELECT COUNT(*) AS n FROM employees")
    check("run_query (SELECT)", rows[0]["n"] == 9, f"{rows[0]['n']} employee rows")

    blocked = await call("run_query", sql="DELETE FROM employees")
    check("run_query blocks mutations", "error" in blocked, blocked.get("error", ""))

    print("7. Write tools")
    joiner = await call(
        "create_employee",
        code="PH-9500",
        name="Smoke Joiner",
        email="smoke.joiner@openhr.com",
        department="Engineering",
        designation="Backend Engineer I",
        joined_on="2026-09-01",
        manager="PH-1042",
        location="Pune",
        band="IC1",
        ctc_minor=120_000_000,
    )
    check(
        "create_employee",
        joiner.get("status") == "probation",
        f"{joiner['code']} · {joiner['name']} · {joiner['ctc_lpa']}",
    )

    joiner_balance = await call("get_leave_balance", employee="PH-9500", year=2026)
    check(
        "create_employee grants entitlements",
        units_of(joiner_balance, "earned") == 36,
        "18 days earned leave from day one",
    )

    overdrawn = await call(
        "request_leave",
        employee="PH-9500",
        leave_type="earned",
        start_date="2026-11-01",
        end_date="2026-12-15",
        days=25,
        reason="more than the quota",
    )
    check("request_leave REJECTS overdraft", "error" in overdrawn, overdrawn.get("error", ""))

    quarter = await call(
        "request_leave",
        employee="PH-9500",
        leave_type="casual",
        start_date="2026-11-03",
        end_date="2026-11-03",
        days=0.25,
        reason="quarter day",
    )
    check("request_leave REJECTS sub-half-day", "error" in quarter, quarter.get("error", ""))

    request = await call(
        "request_leave",
        employee="PH-9500",
        leave_type="casual",
        start_date="2026-11-03",
        end_date="2026-11-04",
        days=1.5,
        reason="smoke test leave",
    )
    check(
        "request_leave (valid)",
        request.get("status") == "pending",
        f"{request['id']} · {request['days']}",
    )

    reserved = await call("get_leave_balance", employee="PH-9500", year=2026)
    check(
        "pending request RESERVES balance",
        units_of(reserved, "casual") == 21,
        f"24 units entitled, {units_of(reserved, 'casual')} available",
    )

    clash = await call(
        "request_leave",
        employee="PH-9500",
        leave_type="sick",
        start_date="2026-11-04",
        end_date="2026-11-04",
        days=1,
        reason="overlaps the one above",
    )
    check("request_leave REJECTS overlap", "error" in clash, clash.get("error", ""))

    self_approved = await call(
        "decide_leave_request",
        request_id=request["id"],
        decision="approve",
        decided_by="PH-9500",
    )
    check("decide REJECTS self-approval", "error" in self_approved, self_approved.get("error", ""))

    approved = await call(
        "decide_leave_request",
        request_id=request["id"],
        decision="approve",
        decided_by="PH-1042",
        note="fine by me",
    )
    check("decide_leave_request", approved.get("status") == "approved", approved["id"])

    after_approval = await call("get_leave_balance", employee="PH-9500", year=2026)
    check(
        "approval moves NO balance (already reserved)",
        units_of(after_approval, "casual") == 21,
        "reservation made at request time",
    )

    cancelled = await call(
        "cancel_leave_request", request_id=request["id"], reason="smoke test cleanup"
    )
    released = await call("get_leave_balance", employee="PH-9500", year=2026)
    check(
        "cancel_leave_request RELEASES balance",
        cancelled["status"] == "cancelled" and units_of(released, "casual") == 24,
        f"back to {next(b for b in released['balances'] if b['leave_type'] == 'casual')['available']}",
    )

    still_there = await call("list_leave_requests", employee="PH-9500")
    check(
        "cancelled request is preserved, not deleted",
        still_there["total"] == 1,
        "history is append-only",
    )

    granted = await call(
        "grant_leave_entitlement",
        employee="PH-9500",
        leave_type="comp",
        year=2026,
        entitled_days=2,
    )
    check(
        "grant_leave_entitlement",
        units_of(granted, "comp") == 4,
        "2 comp-off days credited",
    )

    assigned = await call(
        "assign_asset",
        asset="AST-0008",
        employee="PH-9500",
        issued_on="2026-09-02",
        condition="good",
        note="smoke test",
    )
    check("assign_asset", assigned.get("status") == "assigned", f"{assigned['tag']} issued")

    double = await call(
        "assign_asset", asset="AST-0008", employee="PH-1088", issued_on="2026-09-03"
    )
    check("assign_asset REJECTS double custody", "error" in double, double.get("error", ""))

    returned = await call(
        "return_asset", asset="AST-0008", returned_on="2026-09-04", condition="damaged"
    )
    check(
        "return_asset (damaged → in_repair)",
        returned.get("status") == "in_repair",
        f"{returned['tag']} is {returned['status']}",
    )

    skipped = await call("advance_candidate", candidate_id="cnd_0005", to_stage="hired")
    check("advance_candidate REJECTS stage skip", "error" in skipped, skipped.get("error", ""))

    advanced = await call(
        "advance_candidate", candidate_id="cnd_0005", to_stage="screening", note="smoke test"
    )
    check(
        "advance_candidate",
        advanced.get("stage") == "screening",
        f"{advanced['name']}: applied → screening",
    )

    promoted = await call(
        "update_employment_status", employee="PH-9500", status="active", reason="smoke test"
    )
    check("update_employment_status", promoted.get("status") == "active", "probation → active")

    illegal = await call("update_employment_status", employee="PH-9500", status="probation")
    check("status REJECTS illegal transition", "error" in illegal, illegal.get("error", ""))

    print("8. Exit flow")
    exit_started = await call(
        "initiate_exit",
        employee="PH-9500",
        reason="resignation",
        resigned_on="2026-09-05",
        last_working_day="2026-11-05",
        notes="smoke test exit",
    )
    check(
        "initiate_exit",
        exit_started["exit"]["status"] == "clearance_pending" and exit_started["steps_total"] == 5,
        f"{exit_started['steps_total']} clearance steps opened",
    )

    on_notice = await call("get_employee", employee="PH-9500")
    check("initiate_exit moves employee to notice", on_notice["status"] == "notice", "same txn")

    for step in (
        "knowledge_transfer",
        "finance_settlement",
        "access_revoked",
        "exit_interview",
        "assets_returned",
    ):
        final = await call("complete_exit_step", employee="PH-9500", step=step, done_by="PH-1001")
    check(
        "complete_exit_step (all five)",
        final["exit"]["status"] == "completed",
        f"{final['steps_done']}/{final['steps_total']} done",
    )

    gone = await call("get_employee", employee="PH-9500")
    check(
        "exit completes the employment record",
        gone["status"] == "exited" and gone["exited_on"] == "2026-11-05",
        "exited on the recorded last working day, not today",
    )

    blocked_step = await call(
        "complete_exit_step", employee="PH-1015", step="assets_returned", done_by="PH-1001"
    )
    check(
        "asset clearance REFUSED while kit is held",
        "error" in blocked_step,
        blocked_step.get("error", ""),
    )

    print("9. Post-write invariants")
    final_audit = await call("get_audit_log", limit=1)
    check(
        "every mutation left an audit row",
        final_audit["total"] >= 29 + 15,
        f"{final_audit['total']} audit rows",
    )

    orphans = await call(
        "run_query",
        sql="SELECT COUNT(*) AS n FROM assets a WHERE a.status = 'assigned' AND NOT EXISTS ("
        "SELECT 1 FROM asset_assignments g WHERE g.asset_id = a.id AND g.returned_on IS NULL)",
    )
    check("no asset is 'assigned' without a holder", orphans[0]["n"] == 0, "custody consistent")

    overdrafts = await call(
        "run_query",
        sql="SELECT COUNT(*) AS n FROM leave_entitlements e WHERE e.entitled_units < ("
        "SELECT COALESCE(SUM(r.units), 0) FROM leave_requests r "
        "WHERE r.employee_id = e.employee_id AND r.leave_type = e.leave_type "
        "AND CAST(substr(r.start_date, 1, 4) AS INTEGER) = e.year "
        "AND r.status IN ('pending', 'approved'))",
    )
    check("no tracked leave bucket is overdrawn", overdrafts[0]["n"] == 0, "balances hold")

    await container.close()
    print()
    if failures:
        print(f"{FAIL} {len(failures)} FAILED: {failures}")
        sys.exit(1)
    print(f"{PASS} ALL CHECKS PASSED — every tool verified against the seeded SQLite database")


if __name__ == "__main__":
    asyncio.run(main())
