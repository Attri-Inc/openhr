# Claude Connector Setup (MCP)

## 1) Install dependencies

```bash
cd /absolute/path/to/open-hr
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2) Seed the database

```bash
python scripts/seed.py
```

This creates `data/openhr.db` with the demo company: 9 employees across 5
departments, 11 leave requests, 8 assets (7 in someone's hands), 3 requisitions
with 6 candidates and 7 interview rounds, 15 documents, the 2026 holiday
calendar and one exit in progress. Re-running it resets the DB.

> It **deletes and recreates** the database at `OPENHR_DB`. Never point it at
> real employee data.

## 3a) Connect to Claude Code (recommended)

```bash
claude mcp add openhr -s user -- \
  /absolute/path/to/open-hr/.venv/bin/python \
  /absolute/path/to/open-hr/run_mcp.py
```

Then restart Claude Code (or run `/mcp` to check status).

## 3b) Connect to Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` and add:

```json
{
  "mcpServers": {
    "openhr": {
      "command": "/absolute/path/to/open-hr/.venv/bin/python",
      "args": [
        "/absolute/path/to/open-hr/run_mcp.py"
      ],
      "env": {
        "OPENHR_DB": "/absolute/path/to/open-hr/data/openhr.db"
      }
    }
  }
}
```

Then fully quit and reopen Claude Desktop (Cmd+Q, not just close the window).

> **Why the `.venv` python?** The `mcp` package is installed inside the
> virtualenv. Pointing the config at the system `python3` would fail with
> `ModuleNotFoundError: mcp`.

## 4) Verify tools

In Claude, you should see 31 tools named `list_employees`, `get_leave_balance`,
`get_leave_calendar`, `request_leave`, `assign_asset`, `get_exit_checklist`,
`run_query`, etc.

Try asking:

- "Who's out on leave on 15 September 2026?"
- "How much earned leave does Dev Bhatia have left?"
- "What kit is Karan Shah still holding, and is he cleared to leave?"
- "How many people per department, and what's our leave liability?"

A good refusal to see once, so you trust the rest: ask it to book someone 25
days of earned leave. The server will answer with the exact balance instead of
silently going negative.

## Reading the numbers

- **Leave** is stored as integer half-day units (2 units = 1 day). Every
  response also carries a readable `days` string, so `"units": 3` reads as
  `"1.5 days"`.
- **Money** is integer minor units (paise): `420000000` is `₹42.0 LPA`.
- **Rates** are integer basis points: `1250` is `12.50%`.
- A leave request **reserves** balance as soon as it is raised, so a pending
  request already lowers what is available. Approving it moves nothing further.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Server shows "failed" in Claude | Check the python path is the `.venv` one; run `run_mcp.py` manually to see the error |
| Tools return "no such table" | Run `python scripts/seed.py` first |
| `ModuleNotFoundError: mcp` | `pip install -r requirements.txt` inside the venv |
| `No module named 'mcp.server.fastmcp'` | You are on the `mcp` 1.x SDK. OpenHR targets 2.x — `pip install -U 'mcp[cli]>=2.2.0'` |
| Balance looks lower than expected | A pending request is holding it. `list_leave_requests --status pending` for that employee |
