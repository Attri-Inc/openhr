# Contributing to OpenHR

Thanks for your interest in contributing.

## Development setup

```bash
git clone https://github.com/Attri-Inc/open-hr.git
cd open-hr
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python scripts/seed.py        # creates ./data/openhr.db with the demo company
```

Configuration is read from environment variables (see `.env.example` for the
list, e.g. `OPENHR_DB`). There is no automatic `.env` loading — export the
variables in your shell if you want to override the defaults.

> `scripts/seed.py` deletes and recreates the database it points at. Never run
> it against a database holding real employee data.

## Running the MCP server

```bash
python run_mcp.py             # stdio (default — for Claude Desktop / Code)
MCP_TRANSPORT=sse python run_mcp.py
```

## Running the checks

```bash
python scripts/smoke_test.py  # exercises every tool + asserts invariants
pytest                        # unit/integration tests
```

## Linting & types

```bash
ruff check .
ruff format --check .
mypy . --ignore-missing-imports
```

These are the same checks CI runs — run them before pushing.

## Where code goes

The layers are the point; keep them honest.

- `domain/` is pure: constants, policy-as-data, date helpers, error types. No
  I/O, no imports from other layers.
- `repositories/sqlite.py` is the only file allowed to contain SQL. Everything
  else talks to the protocols in `repositories/protocols.py`.
- `services/` is the only layer with business rules. A rule that lives in a tool
  function instead will be missed by the next caller.
- `mcp_server.py` is a transport adapter: resolve the service, call it, map a
  `DomainError` to the error envelope. No logic.
- Adding a report means adding a strategy class in `services/reports.py` and a
  `ReportService` method — nothing existing should change.

## Pull request guidelines

- One logical change per PR. Refactors and feature work go in separate PRs.
- Add or update tests for behavioural changes.
- Update `CHANGELOG.md` under `[Unreleased]`.
- Keep public tool/schema additions documented in `README.md` and `docs/`.
- Never introduce a float into a stored or computed quantity. Leave is integer
  half-day units, money is integer minor units, rates are integer basis points.
- Never weaken a core invariant (leave balances that cannot be overdrawn,
  single-holder asset custody, forward-only state machines, append-only
  history, same-transaction audit rows) without a documented rationale and
  tests.

## Reporting bugs

Open an issue with:
- OpenHR version
- Python version
- Reproduction steps
- Expected vs actual behaviour

Please do not paste real employee data into an issue.

## Reporting security issues

See [SECURITY.md](SECURITY.md). Do not open a public issue for vulnerabilities.

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By
participating, you agree to uphold it.
