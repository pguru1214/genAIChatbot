# TripWeave implementation status

Updated: 5 November 2026. This document describes working code; [PRD.md](PRD.md)
defines the wider target product. This remains a local, single-user development
application, without production authentication.

## India destination scope

- New planning and research support destinations within India only. Travelers
  can live elsewhere and use their preferred budget currency.
- The tourism source registry contains all **28 states and 8 union territories**,
  canonical names, aliases, state/UT website URLs and national tourism references.
- Registered states/UTs and featured districts resolve locally, before travel
  API calls. City geocoding requests use `countryCode=IN`, validate returned
  countries and respect the user's supplied regional/country qualifiers.
- Foreign destinations receive an India-only correction question. Conversations
  retain the other supplied trip details. Saved foreign plans from older versions
  are retained for viewing; their existence does not enable new foreign research.
- Demo mode supports destinations recognized by the local directory. Live mode
  can additionally verify Indian cities through geocoding.

## Tourism directory coverage

The maintained seed is [india_tourism.json](backend/app/data/india_tourism.json).
`GET /api/tourism/directory` exposes its version, review date, sources and coverage.

| Initial detailed state | Featured district records |
| --- | --- |
| Goa | North Goa, South Goa |
| Telangana | Hyderabad, Hanumakonda, Mulugu |
| Andhra Pradesh | Visakhapatnam, Tirupati, Kurnool |
| Karnataka | Mysuru, Kodagu, Vijayanagara |
| Kerala | Ernakulam, Idukki, Alappuzha |
| Rajasthan | Jaipur, Ajmer, Udaipur |

These are **17 featured districts and 34 attraction-name references**, not a
visitor ranking or an exhaustive district database. City/area aliases help route
requests to relevant sources; they do not redefine district boundaries.
Other states/UTs have registered tourism sources, with detailed district curation
still pending. No claim is made that every registered website is always online.

## Source routing and official research

- A LangGraph **India Tourism Router** selects district/source IDs before travel
  research. For state requests, a structured Gemini call considers the question,
  interests and trip length. Its selection is bounded to eight seconds and falls
  back to deterministic catalog ranking when unavailable.
- Backend validation removes unregistered district IDs, prevents selections
  across the catalog's geographic clusters and limits district count: one for
  1–3 days, up to two for 4–5 days, up to three for 6–7 days.
- District requests use their registered district sources. City requests use
  applicable official sources alongside destination and nearby-place adapters.
- The backend retrieves only URLs associated with registered source IDs. It
  does not crawl arbitrary links or fetch model-generated website addresses.
- Official HTML extraction excludes scripts, navigation and other non-content
  blocks, with request timeouts and a one-megabyte response bound. Redirected
  URLs require a reviewed registry correction; redirects are not followed by
  the application adapter.
- Successful extracts are stored in `tourism_page_cache` in PostgreSQL or SQLite.
  The cache is fresh for 24 hours. On source failure, extracts less than seven
  days old may be returned with a stale-data notice. Otherwise retrieval falls
  back to a registered Incredible India source and dated catalog references.
- Source URLs, retrieval/review dates and reference-only/stale labels remain
  available with the answer. Curated names never imply verified opening hours,
  prices, booking availability or current accessibility.
- Refresh is **on demand**. Scheduled refresh, a crawler and a content-management
  interface are not implemented.

## AI planning and conversation

- Gemini integration through LangChain, with structured output validation,
  bounded transient retries and an optional explicitly configured fallback model.
- LangGraph routes research, itinerary generation and action previews; the
  source router supplements the three specialist roles.
- Chat collects destination, departure date, 1–7-day duration, budget, currency,
  interests, companions and time zone. The trip editor can supply corrections.
- Plain dates and common field replies are parsed locally to avoid unnecessary
  model calls. Registered destination replies can also resolve without Gemini.
- Durable clarification and resume use PostgreSQL or SQLite LangGraph
  checkpoints. Reloading a conversation restores its pending question/details.
- Day-by-day itineraries and packing suggestions use supplied preferences and
  evidence. State requests produce suggested regional circuits; district
  requests remain scoped to the district.
- Regional circuits currently do not fetch forecasts for every stop. The app
  explains that a specific base town is needed rather than invent statewide
  weather. Road travel times and transfer logistics remain estimates.
- Saved conversations support follow-up changes; saving a follow-up updates the
  existing trip instead of duplicating it. Revision history is not implemented.

## Supporting travel adapters

- Open-Meteo city geocoding and forecasts within the supported forecast window.
- Wikipedia destination summaries and filtered nearby visitor-place references.
- Optional Geoapify Places when `GEOAPIFY_API_KEY` is configured, with Wikipedia
  nearby-place fallback. It is not required for official tourism research.
- Public Overpass remains a legacy adapter; normal planning does not depend on it.
- Partial provider failures are reported alongside successful evidence. The AI
  must label unsourced activity ideas and estimates. Unknown source IDs in model
  output fail backend validation.

## Interface, storage and previews

- Responsive React/TypeScript chat, trip panel, editable details, quick planner,
  saved journeys, progress messages and source references.
- India-only welcome examples and destination suggestions.
- FastAPI SSE responses for progress, validated answer output and useful errors.
- PostgreSQL or SQLite persistence for trips, conversations, action proposals,
  tourism extracts and graph checkpoints. Development startup creates missing
  tables; deployed schema migrations are still required before production use.
- Trip listing, retrieval and deletion; email/calendar content previews from
  saved plans. **No email is sent and no calendar event is created.**
- Process-local conversation serialization and checkpoint conflict detection
  protect the current single-worker local workflow.

## Validation and remaining work

Automated tests cover country filtering, foreign-destination correction, region
and district routing, source allowlisting, circuit bounds, cache freshness and
outage fallback, a complete state conversation with mocked AI, saved-plan
behavior and existing provider/model failure handling. Tests isolate credentials,
database records and official website requests from the developer environment.
Live public-source checks are separate from mocked integration tests; a green
test suite does not guarantee third-party uptime or AI factual accuracy.

Validation for this increment: **70 backend tests passed**. Live adapter checks
retrieved usable pages for all 17 initial district sources after correcting
redirects and one broken path. A separate, approved synthetic Jaipur request
returned a real Gemini itinerary and packing checklist using official tourism
evidence, without provider notices. The complete state-level conversation was
verified with mocked AI; this does not claim a live Gemini test for every state.

Still planned: nationwide detailed district coverage, source administration and
scheduled refresh, verified road routing/transfer feasibility, forecasts per
circuit stop, authentication and ownership, itinerary revisions, packing progress,
real Gmail/Calendar OAuth and execution, reminders, production migrations and
deployment hardening. No vector database is required for this increment.

## Run the updated backend

Restart FastAPI so the new graph and tourism cache table are initialized. In
Git Bash, from `backend`:

```bash
./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

No new API key is needed. Existing Gemini settings remain in `backend/.env`.
Try a state request such as “Plan four days in Goa with beaches and heritage,”
or “Plan three days in Jaipur district, Rajasthan.” The chat will ask for any
missing dates or preferences before generating the itinerary.

## Reference sources

- [Incredible India national destination directory](https://www.incredibleindia.gov.in/content/incredible-india.html)
- [Goa Tourism Development Corporation](https://goa-tourism.com/)
- [Telangana Tourism](https://tourism.telangana.gov.in/all-destinations)
- [Andhra Pradesh Tourism](https://tourism.ap.gov.in/home)
- [Karnataka Tourism](https://karnatakatourism.org/en/destinations/)
- [Kerala Tourism](https://www.keralatourism.org/)
- [Rajasthan Tourism](https://www.tourism.rajasthan.gov.in/)
- [Open-Meteo geocoding parameters](https://open-meteo.com/en/docs/geocoding-api)
