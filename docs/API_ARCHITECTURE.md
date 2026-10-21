# TripWeave V1 — API Architecture

- **Version:** 1.0
- **Date:** 22 October 2026
- **Status:** Agreed target contract; full implementation pending
- **Related:** [PRD](../PRD.md), [database architecture](DB_ARCHITECTURE.md)

## 1. Service boundaries

React calls one FastAPI application under `/api`. That backend owns identity,
trips, LangGraph runs, evidence, approvals, and integration adapters. A separate
worker processes queued approved actions and due reminders using PostgreSQL.
The three agents are internal components, not separately exposed HTTP services.

This contract defines **37 HTTP operations across 10 groups**. An operation is a
method-and-path pair. It excludes browser preflight requests, generated OpenAPI
documentation, internal tools, and provider APIs.

The current starter exposes only health, trip listing/deletion, `POST /api/chat`
with a direct stream, and a preview-only approval endpoint returning 501. It has
no authentication. The target run/event APIs below replace that prototype flow;
they are not endpoints users can call successfully today.

## 2. Shared contract rules

- JSON request/response bodies except redirects, SSE, and empty 204 responses.
- UUID resource identifiers; ISO 8601 UTC timestamps; date-only trip dates;
  explicit IANA time zones and currency codes.
- Authenticate with a server-managed, HTTP-only session cookie. Use secure cookies
  in deployment, explicit CORS origins, and CSRF protection for mutations.
- Sign-in and integration callbacks validate OAuth state, nonce where applicable,
  redirect allowlists, and PKCE where supported by the chosen flow.
- Never trust client-supplied owner IDs. Scope every resource query to the session.
- Return 404 for missing or inaccessible resources to avoid disclosing ownership.
- Cursor-paginate collections using a stable order and a capped limit, for example
  default 20 and maximum 100. Responses use `{items, next_cursor}`.
- Use `Idempotency-Key` for run creation, proposals, decisions, and reminder
  creation. Bind it to user, operation, and request hash; a changed payload with
  the same key returns 409. Replays return the prior outcome.
- Use resource versions/`If-Match` for conflicting edits; stale writes return 409.
- Mutating requests validate all fields and must not expose provider credentials.
- Provider secrets stay server-side; tool errors are normalized, not returned raw.

## 3. Endpoint inventory — 37 operations

### 3.1 Authentication — 5

| Method | Path | Input / behavior | Success |
| --- | --- | --- | --- |
| GET | `/api/auth/google/start` | Begin sign-in with approved return location | 302 to Google |
| GET | `/api/auth/google/callback` | Validate code/state; establish session | 302 to frontend |
| GET | `/api/me` | Return identity and default time zone | 200 |
| POST | `/api/auth/logout` | Revoke current session and clear cookie | 204 |
| DELETE | `/api/me` | Request account deletion; block new work and revoke access | 202 with deletion state |

The two sign-in routes are unauthenticated but protected by OAuth validation.
All other account operations require a session. Email is not the stable identity.

### 3.2 Google integration — 4

| Method | Path | Input / behavior | Success |
| --- | --- | --- | --- |
| GET | `/api/integrations/google` | Connection status, scopes, usable capabilities; no tokens | 200 |
| POST | `/api/integrations/google/connect` | Requested capabilities: Gmail send and/or Calendar | 200 with authorization URL |
| GET | `/api/integrations/google/callback` | Validate user-bound authorization state and store encrypted tokens | 302 |
| DELETE | `/api/integrations/google` | Disconnect, remove stored tokens, stop affected pending work | 204 |

Use incremental permissions. Sign-in alone must not request Gmail access. OAuth
grants do not replace the separate approval needed for each proposed action.

### 3.3 Trips — 5

| Method | Path | Input / behavior | Success |
| --- | --- | --- | --- |
| POST | `/api/trips` | Title, destination, optional dates/budget/preferences, time zone | 201 with trip |
| GET | `/api/trips` | Cursor, limit, optional status | 200 collection |
| GET | `/api/trips/{trip_id}` | Owned trip and current revision summary | 200 |
| PATCH | `/api/trips/{trip_id}` | Explicit preference/title/date changes and version | 200 |
| DELETE | `/api/trips/{trip_id}` | Block new work, cancel pending operations, remove local trip data | 202 with deletion state |

Trip changes do not silently modify Google events or regenerate emailed content.
Deletion does not implicitly erase external Google resources. Handle in-flight
provider operations through reconciliation before reporting deletion complete.
The same owned-trip GET can report deletion state while cleanup is pending.

### 3.4 Conversations — 3

| Method | Path | Input / behavior | Success |
| --- | --- | --- | --- |
| POST | `/api/trips/{trip_id}/conversations` | Optional title | 201 |
| GET | `/api/trips/{trip_id}/conversations` | Paginated list | 200 collection |
| GET | `/api/conversations/{conversation_id}/messages` | Paginated chronological history | 200 collection |

User messages are created atomically with runs rather than through a separate
message-write request. Assistant messages are persisted after validation.

### 3.5 Runs and streaming — 5

| Method | Path | Input / behavior | Success |
| --- | --- | --- | --- |
| POST | `/api/conversations/{conversation_id}/runs` | Message, optional intent hint, expected trip revision | 202 with run and event URL |
| GET | `/api/runs/{run_id}` | Status, result references, clarification/approval state, safe errors | 200 |
| GET | `/api/runs/{run_id}/events` | Authenticated SSE; optional `Last-Event-ID` | 200 event stream |
| POST | `/api/runs/{run_id}/resume` | Answer to an outstanding clarification and expected checkpoint version | 202 |
| POST | `/api/runs/{run_id}/cancel` | Best-effort cancellation of pending execution | 202 |

The resume endpoint cannot approve external actions. Resume/cancel checks the
run's state and owner. Cancellation does not reverse a completed provider action.

### 3.6 Itineraries and packing — 5

| Method | Path | Input / behavior | Success |
| --- | --- | --- | --- |
| GET | `/api/trips/{trip_id}/itineraries` | Paginated immutable revisions | 200 collection |
| GET | `/api/trips/{trip_id}/itineraries/{revision_id}` | Revision, activities, evidence references | 200 |
| GET | `/api/trips/{trip_id}/packing-items` | Checklist and packed status | 200 collection |
| POST | `/api/trips/{trip_id}/packing-items` | Category and description | 201 |
| PATCH | `/api/packing-items/{item_id}` | Description and/or packed status, version | 200 |

Conversational itinerary edits create a new revision through a workflow run.
Direct activity CRUD and individual packing-item deletion are not added to this
agreed 37-operation baseline; they would be explicit future contract additions.

### 3.7 Action proposals — 4

| Method | Path | Input / behavior | Success |
| --- | --- | --- | --- |
| POST | `/api/trips/{trip_id}/action-proposals` | Revision, action type, targets, selected activities/reminder preferences | 201 preview |
| GET | `/api/action-proposals/{proposal_id}` | Exact immutable preview, approval and per-operation execution status | 200 |
| POST | `/api/action-proposals/{proposal_id}/approve` | Payload hash and expected proposal version | 202 with execution state |
| POST | `/api/action-proposals/{proposal_id}/reject` | Expected proposal version | 200 rejected state |

The Action Agent may propose an action through the same application service, but
never approves it. Approval must match owner, revision, payload, connection,
expiry, and permitted target. V1 emails go to the connected user's own account.
Only application-created Calendar events can be modified or deleted.

Atomically record approval and enqueue work. Retries must not enqueue duplicate
operations. Partial Calendar success is visible per event. Uncertain Gmail
outcomes remain uncertain; do not report success or automatically resend.

### 3.8 Reminders — 4

| Method | Path | Input / behavior | Success |
| --- | --- | --- | --- |
| POST | `/api/trips/{trip_id}/reminders` | Exact email preview/schedule, time zone, optional activity, explicit confirmation | 201 |
| GET | `/api/trips/{trip_id}/reminders` | Paginated states and trigger times | 200 collection |
| PATCH | `/api/reminders/{reminder_id}` | Pending schedule change, expected version, renewed confirmation | 200 |
| DELETE | `/api/reminders/{reminder_id}` | Cancel pending reminder | 204 |

Convert approved local time to UTC at creation. Validate ambiguous dates/times.
Cancellation racing an already executing send can return 409; never promise an
email has been stopped if the provider call may already have happened.

### 3.9 Evidence — 1

| Method | Path | Input / behavior | Success |
| --- | --- | --- | --- |
| GET | `/api/runs/{run_id}/evidence` | Paginated normalized facts, sources, scope, timestamps, availability | 200 collection |

Return only evidence from an owned run. Do not expose raw provider requests,
tokens, private prompts, or unrelated checkpoint content.

### 3.10 Health — 1

| Method | Path | Input / behavior | Success |
| --- | --- | --- | --- |
| GET | `/api/health` | Minimal application/database readiness | 200, or 503 when unready |

This public endpoint reveals no secrets, detailed database errors, or credentials.
Provider outages need not make the entire application unready.

## 4. Representative payloads

### Create a trip

```json
{
  "title": "Jaipur weekend",
  "destination": "Jaipur, India",
  "start_date": "2026-12-11",
  "end_date": "2026-12-13",
  "timezone": "Asia/Kolkata",
  "budget": "15000.00",
  "currency": "INR",
  "preferences": {"interests": ["history"], "pace": "relaxed"}
}
```

These example dates are outside today's short-range forecast window. The system
must explain forecast unavailability rather than generate December weather.

### Start a run

```json
{
  "message": "Plan three days with historical attractions and a packing list.",
  "intent_hint": "plan",
  "expected_trip_version": 1
}
```

Return 202 only after persisting the run and message, for example:

```json
{
  "id": "11111111-1111-4111-8111-111111111111",
  "status": "queued",
  "events_url": "/api/runs/11111111-1111-4111-8111-111111111111/events"
}
```

An intent hint is untrusted input, not authorization to call any tool.

### Approve an action

```json
{
  "payload_hash": "sha256:EXACT_PREVIEW_HASH",
  "expected_proposal_version": 1
}
```

The server derives ownership and approved payload from stored records, not a
replacement body supplied during approval. The placeholder hash is illustrative.

## 5. SSE contract

Persist events with a monotonic sequence per run. Stream authenticated events
with an event ID, type, run ID, timestamp, and minimal payload:

```text
id: 12
event: progress
data: {"run_id":"11111111-1111-4111-8111-111111111111","timestamp":"2026-10-22T10:00:00Z","message":"Researching attractions"}

```

Types: `progress`, `answer_delta`, `sources`, `approval_required`,
`partial_failure`, `completed`, `error`, and `state_snapshot` when replay has
expired. Heartbeats may be SSE comments and need not create database rows.

- Reconnect using `Last-Event-ID`; bounded replay or a state snapshot must not
  restart the run. No new execution is triggered by opening the stream.
- Use cookies or an authenticated fetch stream; never put credentials in URLs.
- Show useful status, not private chain-of-thought, prompts, or raw tool payloads.
- Draft answer tokens are provisional. A completed result must pass validation;
  retract or replace invalid drafts and do not enable actions on draft text.
- Stream disconnection and run cancellation are separate concepts. Limit stream
  count and buffer sizes so slow clients cannot exhaust server resources.

The starter currently emits validated answer chunks after generation; token-level
Gemini streaming, persisted events, and reconnect are pending implementation.

## 6. Internal agent/tool mapping

| Component | Internal operations | Data touched |
| --- | --- | --- |
| Supervisor/router | Validate intent, clarify, dispatch, enforce execution budgets | Owned trip, conversation, run/checkpoint |
| Travel Research Agent | Geocode, retrieve weather, Wikipedia, and Overpass; parallel independent calls | Evidence records and research state |
| Itinerary Agent | Generate structured plan/packing proposals from evidence | New revision, activities, packing suggestions after validation |
| Action Agent | Prepare exact email/Calendar/reminder proposals | Proposal records; no self-approval |
| Backend/worker | Validate approval, send authorized email, mutate permitted events, process reminders | Approvals, executions, mappings, deliveries, reminder states |

Provider adapters enforce schemas, fixed destinations, size limits, timeouts,
bounded retries, and attribution. Location resolution precedes coordinate-based
calls. Parallel branches merge normalized evidence; one failed provider yields
an explicit partial failure. No public endpoint exposes arbitrary SQL, URLs, or
agent execution. Embeddings and document chunking are not needed for V1.

## 7. Errors, safety, and concurrency

Use a stable safe error envelope, for example:

```json
{
  "error": {
    "code": "PROPOSAL_EXPIRED",
    "message": "Preview this action again before approving it.",
    "request_id": "22222222-2222-4222-8222-222222222222"
  }
}
```

| Status | Meaning |
| --- | --- |
| 401 | Missing, expired, or revoked session |
| 403 | Authenticated request lacks a permitted capability or valid CSRF check |
| 404 | Resource missing or outside the user's scope |
| 409 | Stale version, invalid state transition, changed idempotency payload, cancellation race |
| 410 | Expired approval; a new proposal is required |
| 422 | Invalid fields, dates, time zone, or incomplete required action details |
| 429 | Application/provider quota or execution budget exceeded; include retry guidance where known |
| 502/503/504 | Provider failure, unavailable prerequisite, or timeout before an asynchronous run is accepted |

After 202 acceptance, report execution failures through run/action status and SSE;
do not pretend an already accepted HTTP response can change its status later.
Do not expose raw provider exception strings. Validate source IDs, date ranges,
and itinerary constraints; an LLM's agreement is not proof of ground truth.

Avoid long database transactions around API calls. Enforce expected versions and
unique request/operation keys. Workers use claimed persistent rows; provider
timeouts can have ambiguous outcomes and must not be handled as blind retries.

## 8. Implementation and contract validation

1. Add identity and Alembic-backed domain schema before enabling multi-user access.
2. Introduce versioned run/status/event contracts and migrate React from `/api/chat`.
3. Add durable LangGraph checkpoints, evidence storage, selective routing, and
   parallel tool execution while preserving data ownership.
4. Add immutable proposals, authorization-bound approvals, and execution ledger.
5. Implement Google OAuth and live adapters, then persistent reminder processing.
6. Test ownership for every route, request replay, stale/expired approvals,
   partial provider failures, restart/resume, stream reconnect, and duplicate writes.

Generate OpenAPI from implemented FastAPI schemas and validate it against this
inventory. Use provider fixtures for deterministic contract tests plus separate
live integration checks. Keep current implemented behavior clearly documented
during the transition; this design does not activate any new endpoint by itself.
