# Free transport search

The journey panel searches the selected transport mode using the itinerary's
origin, destination and date. It supports outward, return and between-base legs,
date changes, station/airport selection, and sorting the returned offers by fare
or duration. AI planning estimates remain labelled separately.

Without provider accounts, all three modes offer external route/date search
links. No services, seats or fares are invented. The UI does not book tickets.

## Optional activation

1. Create a **Free personal/evaluation** RailCore account using
   [RailCore pricing](https://railcore.tech/pricing). Enable `stations:read`,
   `journeys:read` and `availability:read` scopes on its API key.
2. Create a free Travelpayouts account and obtain an Aviasales Data API token.
   Follow the [official Data API documentation](https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API).
   Access remains subject to provider approval and terms.
3. Set these variables in ignored `backend/.env`, then restart the backend:

   ```dotenv
   APP_MODE=live
   RAILCORE_API_KEY=your_free_key
   TRAVELPAYOUTS_API_TOKEN=your_token
   ```

For Render, set the same variables in the service's environment settings. Keep
keys on the backend. Do not commit them or add them to Vite variables.

RailCore currently advertises 500 monthly, 100 daily and 10 per-minute free
requests. Local caps are 450 per rolling 31 days, 80 per day and 8 per minute;
station lookups also count. Provider limits remain authoritative, particularly
on ephemeral hosting where local counters can reset. No paid fallback or retry
is attempted. Recheck provider terms before activating; avoid paid plans/trials.

Flight results are cached searches, not live seat inventory or a complete
timetable. Empty cache results do not mean flights are unavailable. Train class
summaries may be old; **Check seats** makes a separate enquiry and shows the
source timestamp. All booking availability and prices require provider confirmation.

No dependable permanently free Indian bus inventory API was verified, so bus
results use external search and redBus links. No unofficial scraping is used.
Changing a transport search date does not reschedule the itinerary. Applying a
chosen service's times to sightseeing remains future work.
