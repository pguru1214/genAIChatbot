"""Read-only, fixed-destination API adapters exposed as typed LangChain tools."""
import asyncio
from datetime import date, datetime, timedelta, timezone

import httpx
from langchain_core.tools import tool


HEADERS = {'User-Agent': 'TripWeave/0.1 (https://github.com/pguru1214/genAIChatbot; local travel research)',
           'Accept': 'application/json'}
OVERPASS_URLS = ('https://overpass-api.de/api/interpreter',
                 'https://overpass.private.coffee/api/interpreter')
TRANSIENT_STATUS = {429, 500, 502, 503, 504}


async def fetch(url: str, params: dict):
    # Only callers in this module choose URLs. Never accept a model-supplied URL.
    async with httpx.AsyncClient(timeout=12, headers=HEADERS, follow_redirects=False) as client:
        for attempt in range(2):
            try:
                # Overpass recommends form POST; avoid long query strings on gateways.
                response = await client.post(url, data=params) if url in OVERPASS_URLS else await client.get(url, params=params)
                response.raise_for_status()
                if len(response.content) > 2_000_000:
                    raise ValueError('Provider result too large')
                return response.json()
            except httpx.HTTPStatusError as error:
                if attempt or error.response.status_code not in TRANSIENT_STATUS:
                    raise
                if url in OVERPASS_URLS and error.response.status_code == 429:
                    # Public Overpass asks clients to pause at least 30 seconds.
                    # Fail this instance instead of retrying before that cooldown.
                    raise
                retry_after = error.response.headers.get('Retry-After', '')
                # Do not retry early when the provider requests a longer cooldown.
                if retry_after and (not retry_after.isdigit() or int(retry_after) > 2):
                    raise
                await asyncio.sleep(max(0.5, float(retry_after or 0)))
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt:
                    raise
                await asyncio.sleep(0.5)


class DestinationNeedsClarification(ValueError):
    """A safe, public location question that can be shown to the user."""

    def __init__(self, message: str, choices: list[str] | None = None):
        super().__init__(message)
        self.choices = choices or []


@tool
async def resolve_destination(destination: str) -> dict:
    """Resolve a destination into candidate cities and coordinates; ambiguity needs user input."""
    parts = [part.strip() for part in destination.split(',') if part.strip()]
    city = parts[0] if parts else destination
    data = await fetch('https://geocoding-api.open-meteo.com/v1/search', {'name': city, 'count': 10, 'language': 'en'})
    candidates = data.get('results', [])
    if len(parts) > 1:
        candidates = [candidate for candidate in candidates if all(
            hint.casefold() in {str(candidate.get(key, '')).casefold()
                               for key in ['country', 'country_code', 'admin1', 'admin2', 'admin3', 'admin4']}
            for hint in parts[1:])]
    if not candidates:
        raise DestinationNeedsClarification('Destination not found. Please give the city, region, and country, separated by commas.')
    # Prefer an exact city name; never silently choose among multiple exact matches.
    exact = [c for c in candidates if c['name'].casefold() == city.casefold()]
    options = exact or candidates
    if len(options) > 1:
        choices = list(dict.fromkeys(', '.join(str(value) for value in [c['name'], c.get('admin1'), c.get('country')] if value) for c in options))
        raise DestinationNeedsClarification(f'I found more than one place named {city}. Please select the city you mean.', choices)
    c = options[0]
    return {k: c.get(k) for k in ['name', 'admin1', 'country', 'latitude', 'longitude', 'timezone']}


@tool
async def get_weather(latitude: float, longitude: float, start_date: str, days: int) -> dict:
    """Fetch weather within the next 16 days. Never extrapolate unsupported forecast dates."""
    start = date.fromisoformat(start_date)
    end = start + timedelta(days=days - 1)
    today = datetime.now(timezone.utc).date()
    if start < today or end > today + timedelta(days=15):
        return {'available': False, 'reason': 'Requested dates are outside this adapter’s 16-day forecast window.'}
    return await fetch('https://api.open-meteo.com/v1/forecast', {
        'latitude': latitude, 'longitude': longitude, 'start_date': str(start), 'end_date': str(end),
        'daily': 'temperature_2m_max,temperature_2m_min,precipitation_probability_max', 'timezone': 'auto',
    })


@tool
async def get_destination_summary(destination: str) -> dict:
    """Find a Wikipedia destination summary with a reference link."""
    data = await fetch('https://en.wikipedia.org/w/api.php', {
        'action': 'query', 'generator': 'search', 'gsrsearch': destination,
        'gsrlimit': 1, 'prop': 'extracts|info', 'exintro': 1, 'explaintext': 1,
        'inprop': 'url', 'format': 'json', 'exchars': 3000,
    })
    pages = list(data.get('query', {}).get('pages', {}).values())
    return {'title': pages[0].get('title'), 'summary': pages[0].get('extract'), 'url': pages[0].get('fullurl')} if pages else {'summary': 'No summary found'}


@tool
async def search_attractions(latitude: float, longitude: float) -> dict:
    """Find named tourist attractions within 8 km using a bounded Overpass query."""
    lat, lon = float(latitude), float(longitude)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError('Invalid coordinates')
    query = f'[out:json][timeout:10];nwr(around:8000,{lat},{lon})[tourism~"^(attraction|museum|viewpoint)$"][name];out center 12;'
    for endpoint in OVERPASS_URLS:
        try:
            # A stalled public server must leave time for the fallback and model.
            async with asyncio.timeout(16):
                data = await fetch(endpoint, {'data': query})
            # Overpass can return HTTP 200 with a query timeout instead of results.
            if data.get('remark'):
                raise ValueError('Attraction lookup exceeded provider resources')
            break
        except httpx.HTTPStatusError as error:
            if error.response.status_code not in TRANSIENT_STATUS or endpoint == OVERPASS_URLS[-1]:
                raise
        except (httpx.TransportError, TimeoutError, ValueError):
            if endpoint == OVERPASS_URLS[-1]:
                raise
    return {'places': [
        {'name': e['tags']['name'], 'type': e['tags'].get('tourism'),
         'opening_hours': e['tags'].get('opening_hours'),
         'url': f"https://www.openstreetmap.org/{e['type']}/{e['id']}"}
        for e in data.get('elements', [])[:12]
    ]}


async def collect_evidence(request: dict, demo: bool) -> dict:
    if demo:
        return {'mode': 'demo', 'location': {'name': request['destination']}, 'evidence': [
            {'id': 'demo-1', 'provider': 'Sample data', 'retrieved_at': datetime.now(timezone.utc).isoformat(),
             'data': {'summary': 'Illustrative data only. Enable live mode for destination-specific research.',
                      'places': [{'name': 'Sample museum'}, {'name': 'Sample city park'}]}, 'url': None}
        ], 'errors': []}
    location = request.get('_resolved_location') or await resolve_destination.ainvoke({'destination': request['destination']})
    coords = {'latitude': location['latitude'], 'longitude': location['longitude']}
    jobs = [get_destination_summary.ainvoke({'destination': request['destination']}), search_attractions.ainvoke(coords)]
    names = ['Wikipedia', 'OpenStreetMap']
    urls = ['https://en.wikipedia.org', 'https://www.openstreetmap.org/copyright']
    if request.get('start_date'):
        jobs.append(get_weather.ainvoke({**coords, 'start_date': request['start_date'], 'days': request['days']}))
        names.append('Open-Meteo')
        urls.append('https://open-meteo.com/')
    results = await asyncio.gather(*jobs, return_exceptions=True)
    evidence, errors = [], []
    for index, (name, url, result) in enumerate(zip(names, urls, results)):
        if isinstance(result, Exception):
            if isinstance(result, httpx.HTTPStatusError):
                reason = f'HTTP {result.response.status_code}'
            elif isinstance(result, (httpx.TimeoutException, TimeoutError)):
                reason = 'request timed out'
            elif isinstance(result, httpx.TransportError):
                reason = 'connection failed'
            else:
                reason = 'lookup could not finish'
            errors.append(f'{name} unavailable ({reason}); no information inferred from this provider.')
        else:
            evidence.append({'id': f'source-{index + 1}', 'provider': name, 'url': result.get('url') or url,
                             'retrieved_at': datetime.now(timezone.utc).isoformat(), 'data': result})
    # A provider outage must not erase the conversation. The planner can return
    # a provisional general outline, with no factual claims or source IDs, and
    # the UI displays the provider failures alongside it.
    return {'mode': 'live', 'location': location, 'evidence': evidence, 'errors': errors}
