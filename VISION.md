# OpenHR Vision

## The problem

HR systems were built for humans clicking through forms, and their data model
shows it: leave balances recomputed in a report, asset custody tracked in a
spreadsheet, an exit checklist that is a set of tick boxes nobody validates. As
agents start handling real people operations — booking leave, chasing clearance,
moving candidates through a funnel — they need a system of record they can both
*read* and *write* with the same fidelity a human gets from an HR UI, and with
guarantees a spreadsheet cannot offer: every balance exact, every custody change
traceable, every approval attributable.

OpenHR is that system of record.

## What OpenHR is

A **local-first HR database** exposed through a Model Context Protocol (MCP)
server, so the people record is queryable and mutable by humans *and* by agents
through the same tools and the same rules.

The data model is deliberately small:

- **`employees`** — the directory and reporting lines, with an employment status
  that moves along a declared state machine.
- **`leave_entitlements` + `leave_requests`** — leave as a balance ledger.
  Entitlement is the bucket; a request draws against it the moment it is raised.
- **`assets` + `asset_assignments`** — custody as an interval, not a field. One
  open assignment per asset, closed on return, never deleted.
- **`requisitions` + `candidates` + `interviews`** — the hiring funnel, where a
  candidate advances one stage at a time.
- **`exits` + `exit_clearance`** — offboarding that gates on the real state of
  the other tables.
- **`audit_log`** — an append-only record of every mutation, written in the same
  database transaction as the change it describes.
- **`org_settings`** — the single-row organisation profile.

## Principles

1. **Correct by construction.** A tracked leave type cannot be overdrawn, an
   asset cannot have two holders, a candidate cannot skip a stage, an exit
   cannot complete with kit outstanding. These are checked in the write path,
   inside one transaction — not in a nightly report.
2. **Exact arithmetic.** Leave is integer half-day units, money is integer minor
   units, rates are integer basis points. There is no float anywhere, so two
   callers can never disagree by a rounding step.
3. **Append-only, not editable.** Decided requests, closed assignments and
   completed exits are history. Corrections are new facts (a cancellation, a
   re-issue), never an overwrite.
4. **Agent-callable from day one.** Every action a human can take is an MCP tool.
   Agents and people operate on the same records through the same rules, and a
   refusal explains what *is* allowed.
5. **Local-first.** Ships as SQLite + a single Python process. Self-hosted; no
   employee data leaves the operator's machine.

## What OpenHR is *not* (v0.1)

- Not payroll. CTC is recorded; salary is not calculated, disbursed or taxed.
- Not attendance. There is no punch-in/punch-out clock or shift roster.
- Not access-controlled at the tool layer. Every caller is trusted; roles exist
  in the reference UI, not yet in the server.
- Not multi-tenant. Each deployment is one company.
- Not a document store. Documents are catalogued; the files live elsewhere.

## Roadmap

### v0.1 (current)
MCP server (31 tools) over a SQLite people database: directory and org chart,
leave balances and approvals, asset custody, the hiring funnel, exits with
clearance, and three people reports (headcount, attrition, leave liability),
all over an append-only audit log.

### v0.2
- REST API twin of every MCP tool (FastAPI, port 8790).
- API-key auth with employee / manager / HR-admin roles mirroring the portal's
  permission matrix; audit actor from the authenticated principal.
- Attendance: regularisation, comp-off accrual from recorded overtime.
- Optimistic locking (`version`) on mutable rows; idempotency keys on writes.

### v0.3
- The [OpenHR Portal](https://openhr-portal.vercel.app) rebuilt as a React +
  TypeScript frontend against the REST API, replacing its in-memory state.
- Hash-chained, tamper-evident audit log with a `verify-audit-chain` command.
- Configurable leave year (the `leave_year_start_month` setting becomes live)
  and carry-forward rules.

### v1.0
- Postgres backend option behind the same repository contracts.
- Multi-region holiday calendars and location-scoped leave policy.
- Stable schema commitment.
