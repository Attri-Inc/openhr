# Security Policy

## Supported versions

OpenHR is in early development. Only the latest minor release receives
security fixes.

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✓         |

## Reporting a vulnerability

Please report security vulnerabilities privately — either via GitHub's
**Security → Report a vulnerability** (private advisory) on this repository, or
by email to **engineering@attri.ai**.

Include:
- A description of the issue
- Steps to reproduce
- Affected version(s)
- Impact assessment if you have one

Please do not file public GitHub issues for security vulnerabilities.

## Disclosure

We follow a coordinated disclosure model. Once a fix is available we will:
1. Release a patched version.
2. Publish a GitHub Security Advisory crediting the reporter (unless they
   prefer to remain anonymous).
3. Update the changelog with the CVE identifier when one has been assigned.

## Hardening notes for operators

OpenHR holds personal data — names, contact details, dates of birth,
compensation, bank-adjacent identifiers in documents, and medical context in
leave reasons. Treat the database file as you would a payroll export.

- **Every tool is unauthenticated in v0.1.** There is no role model in the
  server: any caller that can reach the MCP endpoint can read every employee's
  compensation and write to every record. Expose it only to trusted agents and
  clients. The role matrix in the reference portal is a UI convention, not an
  enforced boundary — see the v0.2 roadmap in [VISION.md](VISION.md).
- The `run_query` tool is read-only by construction: it runs on a dedicated
  connection opened with `PRAGMA query_only=ON` (the engine rejects any write),
  and additionally requires the statement to start with `SELECT`/`WITH` and
  rejects write keywords as a second line of defence. It still permits
  arbitrary **read** access to every table, including `ctc_minor` and
  `expected_ctc_minor`.
- Report grouping is the one place a caller-supplied value reaches SQL as an
  identifier rather than a bound parameter. It is constrained to the
  `HEADCOUNT_DIMENSIONS` allowlist in `src/domain/constants.py`; do not widen it
  to accept arbitrary column names.
- The write tools mutate people records. Mutations are audited in the same
  transaction as the change, so they are traceable — but they are not
  access-controlled at the tool layer in v0.1, and the audit `actor` is the
  literal string `mcp`, not an authenticated principal.
- When running over SSE, keep the default `127.0.0.1` bind (also the default in
  `docker-compose.yml`). Do not publish the port to the LAN.
- The SQLite database file should have filesystem permissions restricted to the
  OpenHR process user, and should be encrypted at rest if the host is shared.
- `scripts/seed.py` **deletes and recreates** the database it points at. Never
  run it against a database holding real employee data.
