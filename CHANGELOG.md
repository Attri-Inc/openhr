# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `streamable-http` transport (served at `/mcp`), the transport remote MCP
  clients expect. Claude Cowork cannot use a local stdio server at all — its
  custom connectors reach a remote MCP URL over the public internet — so this
  is what a Cowork connection requires. `docs/claude-connector.md` gains a
  Cowork section, including why exposing an unauthenticated v0.1 server is
  demo-data-only.
- `MCP_HOST` (default `127.0.0.1`) documented alongside the HTTP transports,
  and an explicit error for an unknown `MCP_TRANSPORT`.

### Changed
- The container and compose file now default to `streamable-http` rather than
  `sse`. The published port stays pinned to the host's loopback interface.

### Changed (cont.)
- `data/openhr.db` is now committed, pre-seeded with the demo company, so a
  clone is runnable without a bootstrap step. `.gitattributes` marks `data/*.db`
  binary so git never attempts a textual merge of a SQLite file. Seeding remains
  the way to reset it; note that a tracked binary shows as modified after any
  local run that writes to it.

### Fixed
- `run_mcp.py` ignored `MCP_TRANSPORT` and always served stdio, so the
  documented `MCP_TRANSPORT=sse python run_mcp.py` silently did nothing. It now
  delegates to `src.mcp_server:main`, keeping stdio as the default.

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
