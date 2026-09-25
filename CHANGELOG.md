# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-09-25

### Added
- MCP server (`src/mcp_server.py`) exposing 31 tools over stdio or SSE:
  directory, org chart, leave balances/requests/calendar, asset custody,
  requisitions and the hiring funnel, exits and clearance, people reports
  (headcount, attrition, leave liability), employee documents, the holiday
  calendar and the audit log — plus safe write tools (`create_employee`,
  `update_employment_status`, `request_leave`, `decide_leave_request`,
  `cancel_leave_request`, `grant_leave_entitlement`, `assign_asset`,
  `return_asset`, `advance_candidate`, `initiate_exit`, `complete_exit_step`)
  and a `run_query` SELECT-only escape hatch.
- SQLite people database: `employees`, `leave_entitlements`, `leave_requests`,
  `assets`, `asset_assignments`, `documents`, `requisitions`, `candidates`,
  `interviews`, `exits`, `exit_clearance`, `holidays`, `audit_log`,
  `org_settings`. Leave is stored as integer half-day units and money as
  integer minor units; there is no float column.
- Core invariants enforced in the write path: tracked leave cannot be
  overdrawn and is reserved at request time, no overlapping live requests,
  one open assignment per asset (also a partial unique index), forward-only
  employment / leave / candidate state machines, exits that gate on real asset
  custody, and an audit row written in the same DB transaction as every
  mutation.
- `scripts/seed.py` bootstraps a fresh dev database from the OpenHR Portal demo
  company (nine employees, leave history, asset custody, three requisitions
  with a live funnel, one exit in progress); it re-checks the seeded data
  through the services and fails loudly if any invariant is violated.
  `scripts/schema.sql` ships the canonical table definitions.
- `scripts/smoke_test.py` exercises every MCP tool and asserts the people
  invariants against the seeded database.
- Dockerfile (non-root) + docker-compose (localhost-bound) for local runs.
- `docs/claude-connector.md` — Claude Desktop / Code setup guide.
- `pyproject.toml` packaging.

### Notes
- Built against the `mcp` 2.x Python SDK (`MCPServer`). SSE now takes its host
  and port as explicit `run()` arguments rather than the v1 `FASTMCP_PORT`
  environment variable, and binds to `127.0.0.1` unless `MCP_HOST` says
  otherwise.

[Unreleased]: https://github.com/Attri-Inc/open-hr/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Attri-Inc/open-hr/releases/tag/v0.1.0
