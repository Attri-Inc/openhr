"""OpenHR MCP Server — 31 tools for people operations.

This module is a thin transport adapter: each tool holds no business logic — it
calls a service (resolved from the composition root) and maps the result (or a
typed DomainError) to a JSON envelope via the serialization helpers.
"""

import os

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from src.config import MCP_ALLOWED_HOSTS, MCP_ALLOWED_ORIGINS, MCP_HOST, MCP_PORT
from src.container import container
from src.domain.errors import DomainError
from src.serialization import error_response, tool_response

mcp = MCPServer(
    "openhr",
    instructions="""
OpenHR is a local-first HR system of record.
It provides tools to query the employee directory and reporting lines, leave
balances and requests, asset custody, the hiring funnel, exits and clearance,
plus people reports (headcount, attrition, leave liability) — and safe write
tools to onboard employees, raise and decide leave, move assets between people,
advance candidates and run an exit.

Conventions that matter when you read results:
- Leave is counted in integer HALF-DAY UNITS: 2 units = 1 day. Every response
  also carries a human-readable `days` string.
- Money is integer minor units (paise): 100 = ₹1.00. CTC is also given in LPA.
- Rates are integer basis points: 10,000 bp = 100%.
- A leave request RESERVES balance as soon as it is raised — pending and
  approved both consume. Corrections are a cancellation, never an edit.
- Employment status, leave status and candidate stage are state machines; an
  invalid move is refused with the list of legal moves.
""",
)


# ---------------------------------------------------------------------------
# Directory (read)
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_employees(
    department: str | None = None,
    status: str | None = None,
    manager: str | None = None,
    include_exited: bool = False,
    q: str | None = None,
) -> str:
    """List the employee directory.
    Filter by department, status (probation, active, notice, exited), manager
    (id/code/email/name), or search by name/code/email.
    Use for "who works in Engineering?", "show everyone on notice"."""
    try:
        return tool_response(
            await container.employees.list_employees(department, status, manager, include_exited, q)
        )
    except DomainError as e:
        return error_response(str(e))


@mcp.tool()
async def get_employee(employee: str) -> str:
    """Get one employee by id, payroll code (e.g. "PH-1042"), email or name,
    with their manager and direct reports.
    Use for "tell me about Sneha Iyer"."""
    result = await container.employees.get_employee(employee)
    if not result:
        return error_response(f"Employee not found: {employee}")
    return tool_response(result)


@mcp.tool()
async def get_org_chart(root: str | None = None, depth: int = 3) -> str:
    """Get the reporting tree below an employee, or the whole company if root is omitted.
    Use for "who reports to Aarav?", "show me the org chart"."""
    try:
        return tool_response(await container.employees.org_chart(root, depth))
    except DomainError as e:
        return error_response(str(e))


# ---------------------------------------------------------------------------
# Leave (read)
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_leave_balance(employee: str, year: int | None = None) -> str:
    """Get an employee's leave balance per type for a year (defaults to this year).
    Entitled minus everything pending or approved gives what is still available.
    Use for "how much earned leave does Dev have left?"."""
    try:
        return tool_response(await container.leave.balance(employee, year))
    except DomainError as e:
        return error_response(str(e))


@mcp.tool()
async def list_leave_requests(
    employee: str | None = None,
    leave_type: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> str:
    """Search leave requests. Filter by employee, type (casual, sick, earned, comp,
    wfh, maternity, unpaid), status (pending, approved, declined, cancelled) or an
    overlapping date range (YYYY-MM-DD).
    Use for "what leave is pending approval?", "show September leave"."""
    try:
        return tool_response(
            await container.leave.list_requests(
                employee, leave_type, status, date_from, date_to, limit, offset
            )
        )
    except DomainError as e:
        return error_response(str(e))


@mcp.tool()
async def get_leave_calendar(date_from: str, date_to: str | None = None) -> str:
    """Who is on approved leave on a date or across a range (YYYY-MM-DD), grouped by department.
    Use for "who's out today?", "who is away next week?"."""
    try:
        return tool_response(await container.leave.calendar(date_from, date_to))
    except DomainError as e:
        return error_response(str(e))


# ---------------------------------------------------------------------------
# Assets (read)
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_assets(
    status: str | None = None,
    category: str | None = None,
    holder: str | None = None,
    q: str | None = None,
) -> str:
    """List company assets with their current holder.
    Filter by status (in_stock, assigned, in_repair, retired), category
    (Laptop, Monitor, Phone, ...), holder (id/code/email/name) or a text search.
    Use for "what laptops are unassigned?", "what does Karan hold?"."""
    try:
        return tool_response(await container.assets.list_assets(status, category, holder, q))
    except DomainError as e:
        return error_response(str(e))


@mcp.tool()
async def get_employee_assets(employee: str, include_returned: bool = False) -> str:
    """Get everything an employee holds, with the outstanding value.
    Set include_returned to see their full custody history.
    Use for "what kit is Karan still holding?"."""
    try:
        return tool_response(await container.assets.employee_assets(employee, include_returned))
    except DomainError as e:
        return error_response(str(e))


# ---------------------------------------------------------------------------
# Recruitment (read)
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_requisitions(status: str | None = None, department: str | None = None) -> str:
    """List manpower requisitions (MRFs) with candidate counts and open positions.
    Filter by status (draft, pending, approved, on_hold, closed) or department.
    Use for "what roles are we hiring for?"."""
    return tool_response(await container.recruitment.list_requisitions(status, department))


@mcp.tool()
async def list_candidates(
    requisition: str | None = None, stage: str | None = None, q: str | None = None
) -> str:
    """List candidates in the hiring funnel.
    Filter by requisition id (e.g. "MRF-2026-014"), stage (applied, screening,
    manager_round, final_round, offer, hired, rejected, withdrawn) or a text search.
    Use for "who is at offer stage?"."""
    try:
        return tool_response(await container.recruitment.list_candidates(requisition, stage, q))
    except DomainError as e:
        return error_response(str(e))


@mcp.tool()
async def get_candidate(candidate_id: str) -> str:
    """Get a candidate with every interview round, scores and the average.
    Use for "how did Ishaan do in his interviews?"."""
    result = await container.recruitment.get_candidate(candidate_id)
    if not result:
        return error_response(f"Candidate not found: {candidate_id}")
    return tool_response(result)


# ---------------------------------------------------------------------------
# Exits (read)
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_exits(status: str | None = None) -> str:
    """List exits in progress or completed.
    Filter by status (initiated, clearance_pending, completed, withdrawn).
    Use for "who is leaving?"."""
    return tool_response(await container.exits.list_exits(status))


@mcp.tool()
async def get_exit_checklist(employee: str) -> str:
    """Get an exit's clearance checklist by exit id or employee, including the
    assets still outstanding and any leave left pending.
    Use for "is Karan cleared to leave?"."""
    try:
        return tool_response(await container.exits.checklist(employee))
    except DomainError as e:
        return error_response(str(e))


# ---------------------------------------------------------------------------
# Reports (read)
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_headcount_report(dimension: str = "department", as_of: str | None = None) -> str:
    """Headcount broken down by department, location, status, employment_type,
    band or designation, optionally as of a date (YYYY-MM-DD).
    Use for "how many people per department?", "headcount at the start of the year"."""
    try:
        return tool_response(await container.reports.headcount(dimension, as_of))
    except DomainError as e:
        return error_response(str(e))


@mcp.tool()
async def get_attrition_report(date_from: str, date_to: str) -> str:
    """Attrition over a period: joiners, leavers and the rate against average headcount.
    Use for "what was our attrition this year?"."""
    try:
        return tool_response(await container.reports.attrition(date_from, date_to))
    except DomainError as e:
        return error_response(str(e))


@mcp.tool()
async def get_leave_liability_report(year: int) -> str:
    """Unused encashable (earned) leave valued at each employee's day rate.
    Use for "what is our leave liability on the books?"."""
    try:
        return tool_response(await container.reports.leave_liability(year))
    except DomainError as e:
        return error_response(str(e))


# ---------------------------------------------------------------------------
# Records & audit (read)
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_employee_documents(employee: str, doc_group: str | None = None) -> str:
    """List an employee's documents, grouped (Joining documents, Compensation &
    appraisal, Compliance & policy, ...).
    Use for "does Meera have her relieving letter on file?"."""
    try:
        return tool_response(await container.records.documents(employee, doc_group))
    except DomainError as e:
        return error_response(str(e))


@mcp.tool()
async def list_holidays(year: int | None = None, region: str | None = None) -> str:
    """List the holiday calendar for a year and region.
    Use for "when is the next holiday?"."""
    return tool_response(await container.records.holidays(year, region))


@mcp.tool()
async def get_audit_log(
    action: str | None = None, actor: str | None = None, limit: int = 25, offset: int = 0
) -> str:
    """Read the append-only audit log of every mutation.
    Actions: create_employee, update_employment_status, request_leave,
    decide_leave_request, cancel_leave_request, grant_leave_entitlement,
    assign_asset, return_asset, advance_candidate, initiate_exit,
    complete_exit_step, complete_exit, seed.
    Use for "who approved that leave?", "show recent activity"."""
    return tool_response(await container.audit.list(action, actor, limit, offset))


# ---------------------------------------------------------------------------
# Directory (write)
# ---------------------------------------------------------------------------


@mcp.tool()
async def create_employee(
    code: str,
    name: str,
    email: str,
    department: str,
    designation: str,
    joined_on: str,
    manager: str | None = None,
    location: str | None = None,
    employment_type: str = "full_time",
    band: str | None = None,
    status: str = "probation",
    ctc_minor: int = 0,
    date_of_birth: str | None = None,
) -> str:
    """Onboard an employee. joined_on is YYYY-MM-DD; ctc_minor is integer paise
    (₹19.5 LPA = 195000000). employment_type: full_time, part_time, contract, intern.
    status must be probation or active. Their leave entitlements for the joining
    year are created in the same transaction.
    Use for "add Priya as a Backend Engineer II in Engineering from 1 Oct"."""
    try:
        return tool_response(
            await container.employees.create(
                code,
                name,
                email,
                department,
                designation,
                joined_on,
                manager,
                location,
                employment_type,
                band,
                status,
                ctc_minor,
                date_of_birth,
                actor="mcp",
            )
        )
    except DomainError as e:
        return error_response(str(e))


@mcp.tool()
async def update_employment_status(
    employee: str, status: str, effective_date: str | None = None, reason: str | None = None
) -> str:
    """Move an employee along the employment state machine
    (probation → active/notice/exited, active → notice/exited, notice → exited/active).
    Exiting requires effective_date (the last working day, YYYY-MM-DD).
    Use for "confirm Meera off probation"."""
    try:
        return tool_response(
            await container.employees.update_status(
                employee, status, effective_date, reason, actor="mcp"
            )
        )
    except DomainError as e:
        return error_response(str(e))


# ---------------------------------------------------------------------------
# Leave (write)
# ---------------------------------------------------------------------------


@mcp.tool()
async def request_leave(
    employee: str,
    leave_type: str,
    start_date: str,
    end_date: str,
    days: float,
    reason: str,
) -> str:
    """Raise a leave request (lands as 'pending' and reserves balance immediately).
    leave_type: casual, sick, earned, comp, wfh, maternity, unpaid.
    Dates are YYYY-MM-DD; days may be whole or half (1, 2.5) and cannot exceed
    the span of the dates. Tracked types cannot be overdrawn.
    Use for "book Dev 2 days casual leave on 22-23 Oct for a family function"."""
    try:
        return tool_response(
            await container.leave.request(
                employee, leave_type, start_date, end_date, days, reason, actor="mcp"
            )
        )
    except DomainError as e:
        return error_response(str(e))


@mcp.tool()
async def decide_leave_request(
    request_id: str, decision: str, decided_by: str, note: str | None = None
) -> str:
    """Approve or decline a pending leave request.
    decision: "approve" or "decline". decided_by is the approver (id/code/email/name)
    and cannot be the requester.
    Use for "approve Tanvi's Goa leave as Fatima"."""
    try:
        return tool_response(
            await container.leave.decide(request_id, decision, decided_by, note, actor="mcp")
        )
    except DomainError as e:
        return error_response(str(e))


@mcp.tool()
async def cancel_leave_request(request_id: str, reason: str) -> str:
    """Cancel a pending or approved leave request, releasing the reserved balance.
    The original stays visible — leave records are never deleted.
    Use for "cancel that leave, the trip is off"."""
    try:
        return tool_response(await container.leave.cancel(request_id, reason, actor="mcp"))
    except DomainError as e:
        return error_response(str(e))


@mcp.tool()
async def grant_leave_entitlement(
    employee: str, leave_type: str, year: int, entitled_days: float
) -> str:
    """Set a tracked leave bucket for a year — credit comp-off, or open a new leave year.
    Tracked types: casual, sick, earned, comp. It cannot be set below what has
    already been used or reserved.
    Use for "give Dev 2 comp-offs for the release weekend"."""
    try:
        return tool_response(
            await container.leave.grant_entitlement(
                employee, leave_type, year, entitled_days, actor="mcp"
            )
        )
    except DomainError as e:
        return error_response(str(e))


# ---------------------------------------------------------------------------
# Assets (write)
# ---------------------------------------------------------------------------


@mcp.tool()
async def assign_asset(
    asset: str,
    employee: str,
    issued_on: str,
    condition: str = "good",
    note: str | None = None,
) -> str:
    """Issue an asset to an employee. asset is an id, tag or serial number;
    issued_on is YYYY-MM-DD; condition: new, good, fair, poor, damaged.
    An asset with an open assignment must be returned first.
    Use for "issue the spare MX Keys to Dev today"."""
    try:
        return tool_response(
            await container.assets.assign(asset, employee, issued_on, condition, note, actor="mcp")
        )
    except DomainError as e:
        return error_response(str(e))


@mcp.tool()
async def return_asset(
    asset: str, returned_on: str, condition: str = "good", note: str | None = None
) -> str:
    """Take an asset back from its current holder. Returned in poor or damaged
    condition sends it to in_repair rather than back into stock.
    Use for "Karan returned his access card today"."""
    try:
        return tool_response(
            await container.assets.return_asset(asset, returned_on, condition, note, actor="mcp")
        )
    except DomainError as e:
        return error_response(str(e))


# ---------------------------------------------------------------------------
# Recruitment (write)
# ---------------------------------------------------------------------------


@mcp.tool()
async def advance_candidate(candidate_id: str, to_stage: str, note: str | None = None) -> str:
    """Move a candidate one stage forward, or to a terminal outcome.
    Funnel order: applied → screening → manager_round → final_round → offer → hired.
    "rejected" and "withdrawn" are reachable from any live stage. A hire needs an
    approved requisition with a position still open.
    Use for "move Ishaan to hired"."""
    try:
        return tool_response(
            await container.recruitment.advance(candidate_id, to_stage, note, actor="mcp")
        )
    except DomainError as e:
        return error_response(str(e))


# ---------------------------------------------------------------------------
# Exits (write)
# ---------------------------------------------------------------------------


@mcp.tool()
async def initiate_exit(
    employee: str,
    reason: str,
    resigned_on: str,
    last_working_day: str,
    notes: str | None = None,
) -> str:
    """Start an exit: records the resignation, opens the five clearance steps and
    moves the employee to 'notice' — all in one transaction.
    reason: resignation, termination, end_of_contract, retirement, absconding.
    Dates are YYYY-MM-DD.
    Use for "Karan resigned today, last working day 30 Nov"."""
    try:
        return tool_response(
            await container.exits.initiate(
                employee, reason, resigned_on, last_working_day, notes, actor="mcp"
            )
        )
    except DomainError as e:
        return error_response(str(e))


@mcp.tool()
async def complete_exit_step(
    employee: str, step: str, done_by: str, note: str | None = None
) -> str:
    """Sign off one clearance step for an exit (by exit id or employee).
    Steps: assets_returned, knowledge_transfer, finance_settlement, access_revoked,
    exit_interview. 'assets_returned' is refused while the person still holds kit.
    Signing off the last step completes the exit and marks the employee exited on
    their last working day.
    Use for "mark Karan's finance settlement done, signed off by Priya"."""
    try:
        return tool_response(
            await container.exits.complete_step(employee, step, done_by, note, actor="mcp")
        )
    except DomainError as e:
        return error_response(str(e))


# ---------------------------------------------------------------------------
# Raw query
# ---------------------------------------------------------------------------


@mcp.tool()
async def run_query(sql: str) -> str:
    """Run a read-only SQL SELECT against the OpenHR database.
    Tables: employees, leave_entitlements, leave_requests, assets,
    asset_assignments, documents, requisitions, candidates, interviews, exits,
    exit_clearance, holidays, audit_log, org_settings.
    Only SELECT is allowed — no mutations.
    Use as an escape hatch when other tools don't cover the question."""
    try:
        return tool_response(await container.queries.run(sql))
    except DomainError as e:
        return error_response(str(e))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


NETWORK_TRANSPORTS: frozenset[str] = frozenset({"sse", "streamable-http"})
TRANSPORTS: frozenset[str] = NETWORK_TRANSPORTS | {"stdio"}

# Always permitted alongside whatever the operator declares, so a local probe
# keeps working when the server is also reachable through a proxy.
LOOPBACK_HOSTS: tuple[str, ...] = ("127.0.0.1:*", "localhost:*", "[::1]:*")


def transport_security() -> TransportSecuritySettings | None:
    """Build the Host/Origin allowlist for the HTTP transports.

    Returning None leaves the SDK's own default in place: it enables DNS-rebinding
    protection for loopback binds and allows only loopback hosts. That is correct
    for a local server and wrong the moment one sits behind a tunnel or reverse
    proxy, where the Host header carries the public name — hence MCP_ALLOWED_HOSTS.
    """
    if not (MCP_ALLOWED_HOSTS or MCP_ALLOWED_ORIGINS):
        return None
    hosts = [*MCP_ALLOWED_HOSTS, *LOOPBACK_HOSTS]
    origins = MCP_ALLOWED_ORIGINS or [
        f"https://{host}" for host in MCP_ALLOWED_HOSTS if not host.endswith(":*")
    ]
    return TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=origins)


def main() -> None:
    """Console entry point. Honours MCP_TRANSPORT.

    - `stdio` (default) — Claude Desktop / Claude Code, which spawn the process.
    - `streamable-http` — served at /mcp. The transport remote MCP clients
      (including Claude Cowork's custom connectors) expect.
    - `sse` — the older HTTP transport, kept for existing clients.

    Both network transports bind to loopback by default: employee records do not
    go on the network unless the operator sets MCP_HOST deliberately. Nothing in
    this server authenticates its callers — see SECURITY.md before exposing it.
    """
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport not in TRANSPORTS:
        raise SystemExit(
            f"Unknown MCP_TRANSPORT '{transport}'. Must be one of: {', '.join(sorted(TRANSPORTS))}"
        )
    security = transport_security()
    if transport == "streamable-http":
        mcp.run(
            transport="streamable-http",
            host=MCP_HOST,
            port=MCP_PORT,
            transport_security=security,
        )
    elif transport == "sse":
        mcp.run(transport="sse", host=MCP_HOST, port=MCP_PORT, transport_security=security)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
