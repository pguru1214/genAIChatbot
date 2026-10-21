# TripWeave — travel assistant starter

React + TypeScript + Vite frontend, FastAPI backend, and three LangGraph roles
using LangChain's Gemini integration. PostgreSQL is supported; SQLite is the
default zero-configuration development fallback. **Docker is optional.**

This is a runnable development foundation for [PRD.md](PRD.md), not a completed
implementation of every PRD acceptance criterion. TripWeave is a working name.

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

Live mode calls Open-Meteo geocoding/weather, Wikipedia, Overpass, and Gemini.
Ambiguous destinations need clarification; this starter may reject a lookup
rather than silently pick the wrong location. Requests outside the forecast
window are labelled unavailable. Provider outages can yield partial results.

## Agent architecture

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
and validation**, not token-by-token from Gemini. Disconnect recovery, durable
checkpoints, and approval/resume are future PRD work.

## Implemented and pending

| Capability | Starter status |
| --- | --- |
| React chat, destination/date inputs, saved plans | Implemented |
| FastAPI, SQLite/PostgreSQL persistence | Implemented |
| LangGraph routing, research/itinerary roles, typed API tools | Implemented |
| Gemini structured outputs in live mode | Implemented; requires your credentials |
| Progress SSE and validated answer chunks | Implemented |
| Gmail/Calendar proposals | Preview only; approval endpoint returns 501 |
| Google sign-in, OAuth token management, user isolation | Pending |
| Live email/Calendar actions and durable approvals | Pending |
| Scheduled reminder worker | Pending |
| Conversation history, packing checkboxes, itinerary revisions | Pending |
| Durable graph checkpoints, reconnection, token streaming | Pending |
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

Live results include source links. Wikipedia content is subject to its applicable
CC BY-SA license and attribution requirements. OpenStreetMap data is ©
OpenStreetMap contributors under ODbL; see https://www.openstreetmap.org/copyright.
Weather data is provided by Open-Meteo; verify its current attribution and usage
terms before launch. Providers do not guarantee completeness or current opening
hours, prices, or availability.
