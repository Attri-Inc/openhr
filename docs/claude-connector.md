# Claude Connector Setup (MCP)

## 1) Install dependencies

```bash
cd /absolute/path/to/open-hr
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2) The database

`data/openhr.db` ships with the repo, already seeded — skip this step unless you
want to reset it:

```bash
python scripts/seed.py
```

It rebuilds `data/openhr.db` with the demo company: 9 employees across 5
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

## 3c) Connect to Claude Cowork

**Cowork cannot use a local stdio server.** Local MCP servers configured in
Claude Desktop's `claude_desktop_config.json` are not available in Cowork or on
claude.ai — Cowork reaches connectors as *remote* MCP servers over the public
internet, from Anthropic's IP ranges. Steps 3a and 3b do not apply here.

So OpenHR has to be served over HTTP and reachable from outside your machine.

> ### Read this before you expose it
>
> OpenHR has **no authentication in v0.1**. Anyone who learns the URL can read
> every employee's compensation and write to every record. A tunnel URL is
> effectively public — it is guessable-adjacent, it is not secret, and it is not
> protected by your Anthropic login.
>
> Only ever do this with the **seeded demo company**, never with real employee
> data, and take the tunnel down when you are finished. See
> [SECURITY.md](../SECURITY.md).

### 1. Serve it over streamable HTTP

```bash
MCP_TRANSPORT=streamable-http MCP_PORT=8792 python run_mcp.py
```

The MCP endpoint is `http://127.0.0.1:8792/mcp`. (`sse` is also supported for
older clients; `streamable-http` is the current remote transport.)

Confirm it is up before going further:

```bash
curl -sS http://127.0.0.1:8792/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```

You should get a `result` naming the `openhr` server.

### 2. Give it a public URL

Any HTTP tunnel works, e.g.:

```bash
cloudflared tunnel --url http://127.0.0.1:8792
# or
ngrok http 8792
```

Your connector URL is that public origin plus the MCP path:
`https://<your-tunnel-host>/mcp`.

The alternative, for anything beyond a demo, is to deploy the container
(`docker compose up`) behind a host you control with a reverse proxy that adds
authentication.

### 3. Add it as a custom connector

In Claude, open **Settings → Connectors → Add custom connector**, paste the
`https://<your-tunnel-host>/mcp` URL, and save. OpenHR does not implement OAuth,
so leave the advanced client ID / secret fields blank.

> On Team and Enterprise plans a custom connector must first be enabled by an
> Owner or Primary Owner under **Organization settings → Connectors**. If you do
> not see the option, that is why.

Then enable the OpenHR connector inside your Cowork session.

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
