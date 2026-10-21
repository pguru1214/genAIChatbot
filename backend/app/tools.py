"""Read-only, fixed-destination API adapters exposed as typed LangChain tools."""
import asyncio
from datetime import date, datetime, timedelta, timezone

import httpx
from langchain_core.tools import tool


HEADERS = {'User-Agent': 'TripWeave/0.1 (local travel-planning development app)'}


async def fetch(url: str, params: dict):
    # Only callers in this module choose URLs. Never accept a model-supplied URL.
    async with httpx.AsyncClient(timeout=12, headers=HEADERS, follow_redirects=False) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        if len(response.content) > 2_000_000:
            raise ValueError('Provider result too large')
        return response.json()


@tool
async def resolve_destination(destination: str) -> dict:
    """Resolve a destination into candidate cities and coordinates; ambiguity needs user input."""
    data = await fetch('https://geocoding-api.open-meteo.com/v1/search', {'name': destination, 'count': 5, 'language': 'en'})
    candidates = data.get('results', [])
    if not candidates:
        raise ValueError('Destination not found; include city and country')
    # Prefer an exact city name; never silently choose among multiple exact matches.
    exact = [c for c in candidates if c['name'].casefold() == destination.casefold()]
    options = exact or candidates
    if len(options) > 1:
        raise ValueError('Ambiguous destination. Try a more specific location: ' + '; '.join(f"{c['name']} ({c.get('admin1', '')}, {c.get('country', '')})" for c in options))
    c = options[0]
    return {k: c.get(k) for k in ['name', 'country', 'latitude', 'longitude', 'timezone']}


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
    data = await fetch('https://overpass-api.de/api/interpreter', {'data': query})
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
    location = await resolve_destination.ainvoke({'destination': request['destination']})
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
            errors.append(f'{name} unavailable; no information inferred from this provider.')
        else:
            evidence.append({'id': f'source-{index + 1}', 'provider': name, 'url': result.get('url') or url,
                             'retrieved_at': datetime.now(timezone.utc).isoformat(), 'data': result})
    if not evidence:
        raise ValueError('Travel providers are unavailable. Try again later.')
    return {'mode': 'live', 'location': location, 'evidence': evidence, 'errors': errors}
