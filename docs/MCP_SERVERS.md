# TripWeave MCP servers

Three independent Python MCP servers expose the existing provider adapters. They
do not call Gemini, create bookings, save trips, or require the frontend/FastAPI
server to run. The existing application still uses its in-process LangGraph
workflow; switching that workflow to MCP is a separate integration step.

| Server | Tools | Local HTTP port |
| --- | --- | --- |
| `travel` | `resolve_destination`, `get_destination_summary`, `get_weather`, `search_transport` | 8101 |
| `accommodation` | `search_stays`, `search_restaurants` | 8102 |
| `attractions` | `search_attractions`, `get_tourism_directory`, `get_official_tourism` | 8103 |

Each server is a separate process with its own tool registry. They share the
existing Python business logic, provider configuration, tourism database cache,
and on-disk Geoapify allowance ledger. This avoids duplicate provider code and
keeps the free API allowance coordinated across processes on this machine.
Separate machines would need a shared allowance store before sharing an API key.

## Install and launch

From the repository root, install the locked backend environment:

```powershell
uv sync --project backend --frozen
```

Start one server per client/process using stdio (the default):

```powershell
./backend/.venv/Scripts/python.exe ./backend/run_mcp.py travel
./backend/.venv/Scripts/python.exe ./backend/run_mcp.py accommodation
./backend/.venv/Scripts/python.exe ./backend/run_mcp.py attractions
```

These commands are alternatives to run in separate processes, not a sequence in
one terminal: each command stays running and waits for MCP messages on stdin.
Stdout carries protocol messages only; logging goes to stderr. Clients should
launch these commands themselves. Client-specific configuration is deferred.

For local HTTP development, run each command in a separate terminal:

```powershell
./backend/.venv/Scripts/python.exe ./backend/run_mcp.py travel --transport streamable-http
./backend/.venv/Scripts/python.exe ./backend/run_mcp.py accommodation --transport streamable-http
./backend/.venv/Scripts/python.exe ./backend/run_mcp.py attractions --transport streamable-http
```

The endpoints are `http://127.0.0.1:8101/mcp`, `:8102/mcp`, and `:8103/mcp`.
Use `--port` to override the default. HTTP binds to loopback only and has no
application authentication; remote hosting is outside this implementation.
The launcher normalizes its working directory to `backend`, so an absolute
launcher path works from other directories and SQLite paths stay consistent.
On Linux/macOS use `backend/.venv/bin/python` instead of the Windows interpreter.

If your terminal is already inside `backend`, use these paths instead (one per
terminal for HTTP):

```powershell
./.venv/Scripts/python.exe ./run_mcp.py travel --transport streamable-http
./.venv/Scripts/python.exe ./run_mcp.py accommodation --transport streamable-http
./.venv/Scripts/python.exe ./run_mcp.py attractions --transport streamable-http
```

With the backend virtual environment activated, each command can be shortened to
`python run_mcp.py <server> --transport streamable-http`. Omit `--transport` for
stdio clients. Running `python main.py` starts the application's API on port 8000;
it does not start the standalone MCP servers. Do not run `python app/main.py`:
the application module is loaded by the `backend/main.py` launcher through Uvicorn.

## Configuration and data limits

Configuration comes from `backend/.env` and environment variables (environment
variables take precedence). Never put keys into tool arguments or client prompts.

- `GEOAPIFY_API_KEY`: required for stays and restaurants; optional for attractions,
  which fall back to Wikipedia. Existing daily credit limits still apply.
- `RAILCORE_API_KEY`, `TRAVELPAYOUTS_API_TOKEN`: optional transport providers.
  Transport retains the application's `APP_MODE=live` requirement; demo mode
  returns its existing demo notice without provider calls. Bus returns search links.
- `DATABASE_URL`: used for the existing official tourism page cache. Its tables
  are initialized on the first official-tourism lookup. Discovery and other tools
  do not require a running database.
- Destination resolution, summaries, nearby attractions, weather and venue tools
  perform real research when called, regardless of `APP_MODE`. They never produce
  fictional demo listings. No Gemini key is needed by these servers.

Destination tools preserve the existing India policy. Coordinate tools accept
validated global coordinates; they do not infer country from a bounding box.
Weather requests accept 1–7 days within the provider's 16-day forecast window.
Stays/restaurants return up to three listings within a 100–10,000 metre radius;
type, dietary, cuisine and accessibility filters use the existing provider fields.
No room prices, ratings or live room inventory are available from these adapters.
There is no hotel-details endpoint because the current provider integration has
no independently verified details API. Official tourism accepts destination names,
not arbitrary URLs, and preserves dated catalog and stale-cache warnings.

## Result contract

Every tool returns structured content plus a text representation:

```json
{
  "status": "ok",
  "retrieved_at": "2026-11-17T00:00:00+00:00",
  "data": {},
  "notices": []
}
```

`status` is `ok`, `unavailable`, or `needs_clarification`. `ok` means the tool
executed; inspect provider-specific `data.status`, `data.notice`, `data.notices`,
and `data.limitations` before making claims. Empty search results mean no matching
listings were returned, not that no venues/services exist. Preserve source URLs,
attribution and original source timestamps. The envelope timestamp records tool
completion, not when a cached source was refreshed. Ambiguous destinations return
`data.choices` and `data.field`. Invalid arguments produce MCP tool errors before
provider execution. Provider failures return sanitized messages without raw URLs,
API keys, or database connection strings. Calls have a 45-second overall deadline;
existing shorter provider budgets and fallback rules remain in force.

## Verification

```powershell
uv run --project backend --frozen pytest backend/tests/test_mcp_servers.py -q
```

Tests cover tool discovery/schemas, input validation, sourced results, venue
preferences, clarification, timeout/cancellation, secret-safe errors and transport
statuses. Real subprocess stdio tests initialize each server, discover tools,
execute an offline call, and check invalid arguments from an unrelated working
directory. HTTP tests also initialize, discover and call each server through its
Streamable HTTP ASGI app. Provider calls are mocked; this does not certify live
vendor uptime.

SDK: the supported [official Python SDK 1.x line](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)
is bounded to `>=1.28,<2` and locked in `backend/uv.lock`; this keeps the tested
FastMCP API stable instead of implicitly upgrading to SDK 2.x.
