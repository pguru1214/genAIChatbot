# TripWeave — travel assistant starter

React + TypeScript + Vite frontend, FastAPI backend, and three LangGraph roles
using LangChain's Gemini integration. PostgreSQL is supported; SQLite is the
default zero-configuration development fallback. **Docker is optional.**

This is a runnable development foundation for [PRD.md](PRD.md), not a completed
implementation of every PRD acceptance criterion. TripWeave is a working name.

New planning is **India-only**. The tourism directory covers all states and UTs,
with initial detailed records for 17 featured districts across six states.
State requests use a tourism-source router and suggested regional circuits.
Official pages are fetched on demand and cached; website availability and district
coverage are explicitly reported. See [implemented features and limitations](IMPLEMENTED_FEATURES.md).

Planning now asks for a starting city and creates timed daily activities with
visit lengths, transfers, meals, next attractions and conditional travel options.
Omitted preferences default to departure in seven days, a 50,000 total budget
(INR unless changed), and 10:00–18:00 daily hours. Transport estimates and
verification links need no new API key; live schedules/fares are not connected.
Long/overnight travel is kept outside the sightseeing clock. If arrival timing
or a day's activities cannot be reconciled, the app preserves usable days and
shows a clearly labeled draft with review notes. Relaxed days may leave free
time. Use the saved-turn retry button after a failure rather than re-entering
the trip; identical failed submissions resume the existing checkpoint.

## Architecture reference

- [Final V1 PRD](PRD.md)
- [Implemented features](IMPLEMENTED_FEATURES.md)
- [Database architecture](docs/DB_ARCHITECTURE.md): 18 application tables,
  provider data mapping, ownership, transactions, and migration plan.
- [API architecture](docs/API_ARCHITECTURE.md): 37 target operations, request
  contracts, streaming, approvals, and error handling.

These architecture documents describe the complete V1 target; they distinguish
that design from the smaller currently implemented starter.

## Prerequisites

- Python **3.11–3.13** (tested with 3.12).
- Node.js **22.12+** (tested with 24) and npm.
- Optional: a PostgreSQL database, installed locally or hosted.
- Optional: a Gemini API key and an available model for live mode.

## Clone and open in VS Code

```sh
git clone https://github.com/pguru1214/genAIChatbot.git
cd genAIChatbot
code .
```

## 1. Start the Python service — no Docker required

In a VS Code terminal:

```sh
cd backend
python -m venv .venv
```

Use Python 3.11–3.13 to create this environment; Python 3.14 is outside the
supported range. On Windows, explicitly select the version with
`py -3.13 -m venv .venv` (install Python 3.13 first if it is unavailable).
An existing environment created with 3.14 must be replaced with a supported one.

For **Windows Git Bash**, activate with `source .venv/Scripts/activate`.
Check `python --version` before installing: it must show 3.11, 3.12, or 3.13.
Run the install commands from `backend`, where `requirements.txt` lives.

Activate the environment on **Windows PowerShell**:

```powershell
.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
```

Or on **macOS/Linux**:

```sh
source .venv/bin/activate
cp .env.example .env
```

Then install the locked dependencies and run the service:

```sh
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

If your Windows policy prevents activation, invoke `.venv\Scripts\python.exe`
directly instead of changing system execution policy. Run commands from `backend`
so the application finds its `.env` and development database.

API documentation is served at `/docs` on port 8000. Health is `GET /api/health`.

On Windows, VS Code **Terminal > Run Task > Backend: run** starts the service
with `backend/.venv/Scripts/python.exe` explicitly, even if an old terminal is
using a different Python. **Backend: install dependencies** uses that same
environment. The **FastAPI: TripWeave** debug configuration also selects it.
From Git Bash in `backend`, you can bypass activation entirely:

```sh
./.venv/Scripts/python.exe -m pip install -r requirements.txt
./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## 2. Start React

Open a **second terminal** at the repository root:

```sh
cd frontend
npm ci
npm run dev
```

Open the address printed by Vite in your own local browser (normally port 5173).
Vite proxies `/api` to FastAPI on port 8000; no frontend API key is needed.
On Windows, use `npm.cmd` if PowerShell blocks the npm script shim.

## 3. Choose your database

For an existing local PostgreSQL database created in pgAdmin, run from `backend`
in Windows Git Bash:

```sh
./.venv/Scripts/python.exe setup_postgres.py
```

Enter your connection details (defaults: localhost, 5432, tripweave, postgres).
The password prompt is hidden. The command verifies the connection, creates the
`trips` and `action_proposals` tables if missing, and saves `backend/.env` only
after success. Restart the backend, then refresh **Schemas > public > Tables**
in pgAdmin. Existing SQLite plans are not migrated.

The default `DATABASE_URL=sqlite:///./tripweave.db` starts immediately with no
database installation. For PostgreSQL, create a database and set this in
`backend/.env`, using your own database's credentials:

```dotenv
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE
```

Use the TLS parameters required by your hosted provider. URL-encode special
characters in connection credentials. Restart FastAPI after changing `.env`.
Development tables are created automatically; schema migrations and data transfer
between SQLite and PostgreSQL are not implemented yet.

### Optional local PostgreSQL through Docker

As in CrimeBase, Docker can start **only the database**:

```sh
# From the repository root:
docker compose up -d db
```

Then set:

```dotenv
DATABASE_URL=postgresql+psycopg://tripweave:tripweave_local_only@localhost:5432/tripweave
```

These are local-development credentials, not production credentials. If port
5432 is already occupied, use your existing database or change the mapped port
and connection URL. `docker compose down` stops the service while retaining its
volume; deleting the volume deletes its data.

## Demo versus live mode

**Demo mode** is the default. It exercises the graph, SSE responses, and saved
plans with explicitly labelled fictional content. It does not retrieve real
weather or location-specific attractions.

For **live mode**, obtain your own key from Google AI Studio and edit only
`backend/.env`:

```dotenv
APP_MODE=live
GEMINI_API_KEY=YOUR_KEY
GEMINI_MODEL=YOUR_AVAILABLE_MODEL
```

Choose a model supported by your account after checking current Gemini free-tier
quotas, availability, and data terms. Restart the backend. No paid service is
enabled by the application. Free-tier availability is not guaranteed.

Live mode calls Open-Meteo geocoding/weather, Wikipedia, and Gemini. Nearby
visitor places use Geoapify when `GEOAPIFY_API_KEY` is configured, otherwise
Wikipedia GeoSearch with visitor-place category filtering. Geoapify failures
fall back to Wikipedia. The default workflow no longer calls public Overpass.
Ambiguous destinations pause the guided conversation with candidate locations.
Reply with city, region, and country separated by commas (for example,
`Jaipur, Rajasthan, India`); the geocoder filters against those explicit details.
The quick planner may still reject ambiguous requests. Requests outside the forecast
window are labelled unavailable. Provider outages can yield partial results.

## Agent architecture

### Guided trip conversations

Plain ISO dates (including `2027-11-02`), day counts, currency codes, common
companion answers, location selections, and explicit detail-form updates are
processed locally rather than sent to Gemini. The browser's `Asia/Calcutta`
time-zone identifier is accepted. Location lookup runs early; when multiple
places match, select a destination button instead of typing a long address.
Once destination, departure and duration are known, **Build my plan with flexible
preferences** fills only missing optional preferences and starts generation.

The backend keeps the selected `GEMINI_MODEL` as primary. Set the optional
`GEMINI_FALLBACK_MODEL` to an account-supported model to use it after temporary
5xx failures. The primary gets one bounded retry; the fallback gets one attempt.
Authentication failures and exhausted quotas do not trigger model switching.
Wrapped Gemini 503 errors are reported as temporary service overload rather than
an invalid date or an unknown workflow failure. Provider outages can still occur;
no application can guarantee model availability. Secrets stay in `backend/.env`.

The default **Plan through chat** view collects destination, departure date,
duration (1–7 days), total budget, currency, interests, companions, and trip time
zone. LangGraph pauses for missing details, resumes on the same conversation
thread, and hands complete preferences to the research and itinerary workflow.
The resulting itinerary and packing suggestions are saved automatically.

Use **Review or edit trip details** to correct preferences. In demo mode this
editor is the reliable way to supply details; its message parser supports only
simple inputs such as `Plan a Jaipur trip`, ISO dates, and `3 days`. Live mode
uses the configured Gemini model for natural-language extraction. Dates require
an explicit year. Follow-up requests retain the trip preferences and previous
plan. The starter replaces the current saved plan; revision history is still
pending. Existing single-request planning and Google previews remain available
under **Quick planner & saved previews**.

Conversations, messages, and graph checkpoints persist in PostgreSQL when it is
configured. Startup initializes the official PostgreSQL checkpointer tables;
the database account needs table-creation permission for this development setup.
SQLite development uses a companion `*.db.checkpoints` file. Keep both database
files when backing up or restoring a SQLite conversation. The browser remembers
the active conversation ID; **Continue a conversation** restores server history.

Run one backend worker for this local-user milestone. Conversation runs are
serialized and stale tabs receive a conflict instead of overwriting a newer
checkpoint. After an interrupted or failed turn, reopen the conversation and use
**Retry saved turn** to resume its checkpoint. SSE provides node progress and a
final response; automatic stream replay and token streaming remain future work.
Authentication and per-account isolation are not implemented; keep the service
bound to localhost.

New endpoints: `POST/GET /api/conversations`,
`GET /api/conversations/{id}`, and
`POST /api/conversations/{id}/messages` (SSE). Message requests include the latest
`checkpoint_id`, `message`, browser `timezone`, and optional typed `details`
overrides. Changed preferences override extraction from that message. Successful
streams emit `conversation` then `completed`; errors preserve recoverable graph
state. Conversation length is limited to 100 messages in this milestone.

After updating dependencies, Git Bash setup is:

```sh
cd backend
./.venv/Scripts/python.exe -m ensurepip --default-pip
./.venv/Scripts/python.exe -m pip install -r requirements.txt
./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In a second terminal, run `cd frontend` and `npm run dev` from the repository root.
Try `Plan a Jaipur trip`, answer the clarification, refresh, and continue. Backend
regressions run with `python -m pytest -q`; frontend validation uses `npm run build`.

### Specialist roles

1. **Travel Research Agent:** typed read-only LangChain tools, parallel public API
   retrieval, evidence records; answers research-only questions.
2. **Itinerary Agent:** structured Gemini generation from retrieved evidence.
3. **Action Agent role:** deterministic saved-plan email/Calendar preview branch
   in this starter. Live OAuth, LLM action interpretation, and execution are pending.

LangGraph performs selective routing. Weather-only requests skip itinerary
generation; explicit email/Calendar preview buttons skip research. The initial
router uses conservative keyword rules rather than an additional LLM call.
The backend checks source identifiers, but full claim-level factual verification
is not implemented. Read provider/source data before relying on recommendations.

The frontend consumes SSE from `POST /api/chat`: progress, validated answer
chunks, completion, and safe errors. Answer chunks are emitted **after generation
and validation**, not token-by-token from Gemini. The guided conversation uses
`POST /api/conversations/{id}/messages` for streamed progress and saved state,
with durable clarification checkpoints and manual recovery. Automatic event replay,
token-level streaming, and external-action approval/resume remain future work.

## Implemented and pending

| Capability | Starter status |
| --- | --- |
| React chat, destination/date inputs, saved plans | Implemented |
| FastAPI, SQLite/PostgreSQL persistence | Implemented |
| LangGraph routing, research/itinerary roles, typed API tools | Implemented |
| India-only destination scope and nationwide tourism source registry | Implemented; detailed seeds cover 17 featured districts in six states |
| State/district tourism source selection and official page cache | Implemented; on-demand refresh and explicit freshness/coverage limits |
| Gemini structured outputs in live mode | Implemented; requires your credentials |
| Progress SSE and validated answer chunks | Implemented |
| Gmail/Calendar proposals | Preview only; approval endpoint returns 501 |
| Google sign-in, OAuth token management, user isolation | Pending |
| Live email/Calendar actions and durable approvals | Pending |
| Scheduled reminder worker | Pending |
| Conversation history, clarification/resume, saved trip preferences | Implemented for local use |
| Durable conversation checkpoints and manual failed-turn recovery | Implemented |
| Packing checkboxes, itinerary revision history | Pending |
| Automatic stream replay and model-token streaming | Pending |
| Alembic migrations, Tailwind, comprehensive PRD evaluations | Pending |

**Bind to loopback only.** This starter is single-user development software with
no authentication; saved plans are visible to anyone who can access the service.
Do not deploy publicly or use it for sensitive personal data until authentication,
ownership enforcement, and the remaining security controls are implemented.

## Tests and production build

```sh
cd backend
# With the virtual environment active:
python -m pytest -q
```

Tests run against an isolated temporary database and mock public API responses;
they do not spend Gemini quota or send email.

```sh
cd frontend
npm run build
```

Vite builds the frontend to `frontend/dist`. Production serving, TLS, and secure
authentication are separate work; a successful build does not make this ready
for public deployment.

## Dependency maintenance

Python dependencies are declared in `backend/pyproject.toml`, resolved in
`backend/uv.lock`, and exported to `backend/requirements.txt` for ordinary pip
users. With uv installed, use `uv sync --locked` in `backend` instead of pip.
When intentionally updating dependencies, regenerate the lock and export:

```sh
uv lock
uv export --frozen --no-emit-project --output-file requirements.txt
```

JavaScript dependencies are locked in `frontend/package-lock.json`; use `npm ci`
for repeatable installation. Never commit `.env`, `.venv`, or `node_modules`.

## Public data attribution

Public research requests identify this project through its User-Agent, as
required by [Wikimedia's policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy).
Temporary network and server failures receive at most one retry. Geoapify and
Wikipedia place lookups each have a 16-second deadline. Access-denied responses
are not retried, and provider
cooldowns are respected. Public servers can remain unavailable; the response
shows which provider failed, while retaining successful research from others.
Previously saved plans keep their original research results; generate a new plan
after restarting the backend to verify a provider fix.

For the optional dedicated Places API, add your own `GEOAPIFY_API_KEY` to
`backend/.env` and restart the backend. Keep it out of frontend code and Git.
Without a key, named visitor places work through Wikipedia; article coverage is
incomplete and does not verify opening hours, ticket prices, or availability.
The UI displays provider attribution and expandable links to each retrieved
place. The old Overpass adapter remains available for development, but is not
part of normal plan generation.

Live results include source links. Wikipedia content is subject to its applicable
CC BY-SA license and attribution requirements. OpenStreetMap data is ©
OpenStreetMap contributors under ODbL; see https://www.openstreetmap.org/copyright.
Weather data is provided by Open-Meteo; verify its current attribution and usage
terms before launch. Providers do not guarantee completeness or current opening
hours, prices, or availability.
