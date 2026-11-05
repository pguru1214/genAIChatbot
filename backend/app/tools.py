"""Read-only, fixed-destination API adapters exposed as typed LangChain tools."""
import asyncio
from datetime import date, datetime, timedelta, timezone

import httpx
from langchain_core.tools import tool
from app.config import get_settings
from app.places import geoapify_places, wikipedia_places
from app.tourism import (DestinationNeedsClarification, INDIA_ONLY, destination_route,
                         region_location, directory, region_for, collect_official, select_districts)


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


@tool
async def resolve_destination(destination: str) -> dict:
    """Resolve Indian states/districts locally or Indian cities with verified coordinates."""
    route = destination_route(destination)
    if route['scope'] in {'state', 'ut', 'district'}:
        return region_location(route)
    parts = [part.strip() for part in destination.split(',') if part.strip()]
    city = parts[0] if parts else destination
    if route.get('district_id'):
        district = next(d for d in directory()['districts'] if d['id'] == route['district_id'])
        # Provider canonical aliases (Panaji -> Panjim, Margao -> Madgaon).
        city = {'panaji': 'Panjim', 'margao': 'Madgaon', 'mysuru': 'Mysore',
                'cochin': 'Kochi', 'alappuzha': 'Alleppey'}.get(city.casefold(), city)
    data = await fetch('https://geocoding-api.open-meteo.com/v1/search',
                       {'name': city + (', ' + parts[1] if len(parts) > 1 else ''),
                        'count': 20, 'language': 'en', 'countryCode': 'IN'})
    candidates = [c for c in data.get('results', []) if c.get('country_code') == 'IN' or c.get('country') == 'India']
    if len(parts) > 1:
        candidates = [candidate for candidate in candidates if all(
            hint.casefold() in {str(candidate.get(key, '')).casefold()
                               for key in ['country', 'country_code', 'admin1', 'admin2', 'admin3', 'admin4']}
            for hint in parts[1:])]
    if not candidates:
        raise DestinationNeedsClarification(INDIA_ONLY + ' I could not verify that destination. Try city, state, India.')
    # Prefer an exact city name; never silently choose among multiple exact matches.
    exact = [c for c in candidates if c['name'].casefold() == city.casefold()]
    options = exact or candidates
    if len(options) > 1:
        choices = list(dict.fromkeys(', '.join(str(value) for value in [c['name'], c.get('admin1'), c.get('country')] if value) for c in options))
        raise DestinationNeedsClarification(f'I found more than one place named {city}. Please select the city you mean.', choices)
    c = options[0]
    return {**{k: c.get(k) for k in ['name', 'admin1', 'country', 'latitude', 'longitude', 'timezone']},
            'country_code': 'IN', 'scope': 'city'}


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


@tool
async def get_visitor_places(latitude: float, longitude: float) -> dict:
    """Find sourced visitor places using Geoapify if configured, otherwise Wikipedia. No Overpass dependency."""
    api_key = get_settings().geoapify_api_key
    if api_key:
        try:
            async with asyncio.timeout(16):
                result = await geoapify_places(latitude, longitude, api_key, fetch)
            if result['places']:
                return result
        except (httpx.HTTPError, ValueError, TimeoutError):
            pass
        async with asyncio.timeout(16):
            result = await wikipedia_places(latitude, longitude, fetch)
        result['notices'] = ['Geoapify returned no usable place data; using sourced Wikipedia nearby places instead.']
        return result
    async with asyncio.timeout(16):
        return await wikipedia_places(latitude, longitude, fetch)


async def collect_evidence(request: dict, demo: bool) -> dict:
    route = request.get('_tourism_route') or destination_route(request['destination'])
    if demo:
        if not route.get('region_id'):
            raise DestinationNeedsClarification(INDIA_ONLY + ' In demo mode, choose a destination from the tourism directory.')
        return {'mode': 'demo', 'location': {'name': request['destination']}, 'evidence': [
            {'id': 'demo-1', 'provider': 'Sample data', 'retrieved_at': datetime.now(timezone.utc).isoformat(),
             'data': {'summary': 'Illustrative data only. Enable live mode for destination-specific research.',
                      'places': [{'name': 'Sample museum'}, {'name': 'Sample city park'}]}, 'url': None}
        ], 'errors': []}
    location = request.get('_resolved_location')
    if not location or not (location.get('country_code') == 'IN' or location.get('country') == 'India'):
        location = await resolve_destination.ainvoke({'destination': request['destination']})
    if not route.get('region_id'):
        region = region_for(location.get('admin1', ''))
        if region:
            route = {**route, 'region_id': region['id'], 'state': region['name']}
    districts = select_districts(route, request, request.get('_district_ids'))
    if route['scope'] in {'state', 'ut', 'district'}:
        evidence, errors = await collect_official(route, districts)
        errors.append('This is a regional circuit suggestion. Weather requires a specific base town; no state-wide forecast is inferred.')
        if not districts:
            errors.append('Detailed district attraction records are not yet curated for this region; official pages provide the available research.')
        return {'mode': 'live', 'location': location, 'tourism_route': route,
                'selected_districts': [d['name'] for d in districts], 'evidence': evidence, 'errors': errors}
    coords = {'latitude': location['latitude'], 'longitude': location['longitude']}
    jobs = [get_destination_summary.ainvoke({'destination': request['destination']}), get_visitor_places.ainvoke(coords)]
    names = ['Wikipedia', 'Nearby visitor places']
    urls = ['https://en.wikipedia.org', 'https://en.wikipedia.org/wiki/Special:Nearby']
    if request.get('start_date'):
        jobs.append(get_weather.ainvoke({**coords, 'start_date': request['start_date'], 'days': request['days']}))
        names.append('Open-Meteo')
        urls.append('https://open-meteo.com/')
    official_job = collect_official(route, districts)
    *results, official = await asyncio.gather(*jobs, official_job, return_exceptions=True)
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
            errors.extend(result.get('notices', []))
            if index == 1 and not result.get('places'):
                errors.append('No nearby visitor places were found in the selected source; the itinerary may include general suggestions.')
            evidence.append({'id': f'source-{index + 1}', 'provider': result.get('provider', name), 'url': result.get('url') or url,
                             'retrieved_at': datetime.now(timezone.utc).isoformat(), 'data': result,
                             'attribution': result.get('attribution'), 'attribution_url': result.get('attribution_url')})
    # A provider outage must not erase the conversation. The planner can return
    # a provisional general outline, with no factual claims or source IDs, and
    # the UI displays the provider failures alongside it.
    if isinstance(official, Exception):
        errors.append('Official tourism information could not be retrieved; using available sources.')
    else:
        extra, notices = official
        evidence.extend(extra)
        errors.extend(notices)
    return {'mode': 'live', 'location': location, 'tourism_route': route, 'evidence': evidence, 'errors': errors}
