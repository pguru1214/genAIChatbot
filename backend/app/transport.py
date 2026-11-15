"""Free-only, read-only transport adapters. No LLM or booking API is used.

RailCore: provider schedules plus a separate fresh seat enquiry.
Aviasales Data API: cached fares, never confirmed seat inventory.
Bus: external searches until a suitable free inventory source is available.
"""
import asyncio
import hashlib
import math
import re
import sqlite3
import time
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from app.config import get_settings
from app.guardrails import has_abuse


router = APIRouter(prefix='/api/transport', tags=['transport'])
RAIL = 'https://ir.railcore.tech/v1'
FLIGHTS = 'https://api.travelpayouts.com/aviasales/v3/prices_for_dates'
AIRPORTS = 'https://autocomplete.travelpayouts.com/places2'
USAGE_PATH = Path(__file__).resolve().parents[1] / '.cache' / 'transport-usage.sqlite3'
_reference_cache = OrderedDict()
INDIA = ZoneInfo('Asia/Kolkata')


class SearchRequest(BaseModel):
    mode: Literal['flight', 'train', 'bus']
    origin: str = Field(min_length=2, max_length=200)
    destination: str = Field(min_length=2, max_length=200)
    date: date
    passengers: int = Field(default=1, ge=1, le=6)
    origin_code: str | None = Field(default=None, max_length=8)
    destination_code: str | None = Field(default=None, max_length=8)

    @field_validator('date')
    @classmethod
    def future_date(cls, value):
        today = datetime.now(INDIA).date()
        if not today <= value <= today + timedelta(days=365):
            raise ValueError('Choose a journey date within the next year.')
        return value

    @field_validator('origin', 'destination')
    @classmethod
    def location(cls, value):
        if not value.strip() or has_abuse(value):
            raise ValueError('Please use a respectful city or station name.')
        return value.strip()

    @field_validator('origin_code', 'destination_code')
    @classmethod
    def code(cls, value):
        if value is None or not value.strip():
            return None
        value = value.strip().upper()
        if not re.fullmatch(r'[A-Z0-9]{2,8}', value):
            raise ValueError('Use a station or IATA code, not a URL.')
        return value


class SeatRequest(BaseModel):
    train_number: str = Field(pattern=r'^[A-Z0-9]{4,6}$')
    origin_code: str = Field(pattern=r'^[A-Z0-9]{2,8}$')
    destination_code: str = Field(pattern=r'^[A-Z0-9]{2,8}$')
    date: date
    travel_class: str = Field(pattern=r'^[A-Z0-9]{1,3}$')

    @field_validator('date')
    @classmethod
    def future_date(cls, value):
        return SearchRequest.future_date(value)


class ProviderIssue(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def city(value):
    if not isinstance(value, str):
        return ''
    first = re.sub(r'\bdistrict\b', '', value.split(',')[0], flags=re.I).strip()
    return first


def canonical(value):
    value = city(value).casefold()
    return {'mysore': 'mysuru', 'bangalore': 'bengaluru', 'cochin': 'kochi', 'panjim': 'panaji',
            'bombay': 'mumbai', 'madras': 'chennai', 'calcutta': 'kolkata', 'alleppey': 'alappuzha',
            'new delhi': 'delhi'}.get(value, value)


def number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (TypeError, ValueError):
        return None


def iso(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.isoformat() if parsed.tzinfo else None
    except ValueError:
        return None


def reserve(provider, key):
    """Conservative rolling limits survive restarts when storage is persistent.

    Provider-side Free-plan caps remain authoritative on ephemeral hosting.
    Failed requests count locally; there are no paid retries or upgrades.
    """
    USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    limits = {'railcore': (450, 80, 8), 'aviasales': (10000, 400, 30), 'airports': (5000, 200, 30)}
    month, day, minute = limits[provider]
    account = hashlib.sha256((provider + ':' + key).encode()).hexdigest()
    with sqlite3.connect(USAGE_PATH, timeout=5) as db:
        db.execute('CREATE TABLE IF NOT EXISTS requests (account TEXT, created REAL)')
        db.execute('BEGIN IMMEDIATE')
        now = time.time()
        db.execute('DELETE FROM requests WHERE created < ?', (now - 31 * 86400,))
        counts = db.execute('SELECT COUNT(*), COALESCE(SUM(created > ?),0), COALESCE(SUM(created > ?),0) '
                           'FROM requests WHERE account = ?', (now - 86400, now - 60, account)).fetchone()
        if any(n >= limit for n, limit in zip(counts, (month, day, minute))):
            raise ProviderIssue('quota_exhausted', 'The free search allowance is reached. Try later or use the provider links.')
        db.execute('INSERT INTO requests VALUES (?, ?)', (account, now))


async def provider_get(provider, url, params):
    settings = get_settings()
    key = settings.railcore_api_key if provider == 'railcore' else settings.travelpayouts_api_token if provider == 'aviasales' else 'public-reference'
    headers = {'Accept': 'application/json'}
    if provider == 'railcore':
        headers['X-RailCore-Key'] = key
    elif provider == 'aviasales':
        headers['X-Access-Token'] = key
    # URLs are chosen exclusively by these adapters, never accepted from a client.
    allowed = {RAIL + '/stations/search', RAIL + '/routes/trains', RAIL + '/availability/seats', FLIGHTS, AIRPORTS}
    if url not in allowed:
        raise ValueError('Unknown transport endpoint')
    await asyncio.to_thread(reserve, provider, key)
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
            response = await client.get(url, params=params, headers=headers)
        if response.status_code in {402, 429}:
            raise ProviderIssue('quota_exhausted', 'The provider free quota is exhausted. No paid fallback was attempted.')
        if response.status_code in {401, 403}:
            provider_name = 'RailCore' if provider == 'railcore' else 'Travelpayouts' if provider == 'aviasales' else 'Airport directory'
            raise ProviderIssue('not_connected', f'{provider_name} denied API access (HTTP {response.status_code}). '
                                'Check the backend API credential and account API permissions. Use the external search links for now.')
        if response.status_code == 422:
            raise ProviderIssue('date_unavailable', 'Availability cannot be checked for this date or class. Booking may not be open yet.')
        response.raise_for_status()
        if len(response.content) > 1_000_000:
            raise ValueError('Provider response too large')
        plan = response.headers.get('x-railcore-plan', '').lower()
        if provider == 'railcore' and plan and plan not in {'free', 'developer_free', 'developer-free'}:
            raise ProviderIssue('free_plan_required', 'Only a Free personal-project provider account is supported.')
        data = response.json()
        if isinstance(data, dict) and data.get('success') is False:
            raise ProviderIssue('provider_error', 'The provider could not complete this search. Check the external links.')
        return data
    except ProviderIssue:
        raise
    except (httpx.HTTPError, ValueError):
        raise ProviderIssue('provider_error', 'The free transport provider is unavailable. Please try later or search externally.') from None


def external_links(request):
    names = {'flight': ('flights', 'https://www.aviasales.com/'),
             'train': ('trains', 'https://www.irctc.co.in/'),
             'bus': ('buses', 'https://www.redbus.in/')}[request.mode]
    query = f'{names[0]} from {city(request.origin)} to {city(request.destination)} on {request.date.isoformat()}'
    return [{'label': 'Search this route and date', 'url': 'https://www.google.com/search?' + urlencode({'q': query})},
            {'label': 'Check ' + ('IRCTC' if request.mode == 'train' else 'redBus' if request.mode == 'bus' else 'Aviasales'),
             'url': names[1]}]


def result_base(request):
    return {'mode': request.mode, 'origin': request.origin, 'destination': request.destination,
            'date': request.date.isoformat(), 'passengers': request.passengers, 'offers': [],
            'origin_points': [], 'destination_points': [], 'origin_code': request.origin_code,
            'destination_code': request.destination_code, 'retrieved_at': utc_now(),
            'links': external_links(request), 'status': 'no_results', 'provider': None,
            'notice': '', 'fare_basis': 'Per adult, as reported; group seat availability and total booking price are not confirmed.'}


async def station_options(value, get):
    marker = ('station', value.casefold())
    if marker in _reference_cache:
        return _reference_cache[marker]
    body = await get('railcore', RAIL + '/stations/search', {'q': city(value), 'limit': 8})
    output = []
    for item in body.get('data', {}).get('results', [])[:8]:
        code = str(item.get('station_code', '')).upper()
        if (item.get('country') or '').upper() != 'IN' or not re.fullmatch(r'[A-Z0-9]{2,8}', code):
            continue
        hints = [v.strip().casefold() for v in value.split(',')[1:] if v.strip().casefold() not in {'india', 'in'}]
        if hints and item.get('state') and item['state'].casefold() not in hints:
            continue
        names = [item.get('city') or '', item.get('station_name') or '', *(item.get('aliases') or [])]
        exact = any(canonical(n) == canonical(value) for n in names)
        output.append({'code': code, 'name': item.get('display_name') or item.get('station_name') or code,
                       'city': item.get('city'), 'state': item.get('state'), 'exact': exact,
                       'major': bool(item.get('is_major'))})
    # Cache reference records only; seats and fares are never cached here.
    if output:
        _reference_cache[marker] = output
        while len(_reference_cache) > 128:
            _reference_cache.popitem(last=False)
    return output


def choose_station(options):
    exact = [p for p in options if p['exact']]
    states = {p.get('state') for p in exact}
    if exact and len(states) <= 1:
        return sorted(exact, key=lambda p: not p['major'])[0]['code']
    return None


async def airport_options(value, get):
    body = await get('airports', AIRPORTS, {'term': city(value), 'locale': 'en', 'types[]': ['city', 'airport']})
    output, seen = [], set()
    for item in body if isinstance(body, list) else []:
        code = str(item.get('code', '')).upper()
        if item.get('country_code') != 'IN' or not re.fullmatch(r'[A-Z]{3}', code) or code in seen:
            continue
        seen.add(code)
        output.append({'code': code, 'name': item.get('name') or code, 'city': item.get('city_name'),
                       'exact': canonical(item.get('name', '')) == canonical(value) or code == value.upper()})
    return output[:8]


def train_offer(row, request):
    train = str(row.get('train_number') or '')
    if not re.fullmatch(r'[A-Z0-9]{4,6}', train):
        return None
    if any(not re.fullmatch(r'[A-Z0-9]{2,8}', str(row.get(k) or '')) for k in ('from_station_code', 'to_station_code')):
        return None
    departure, arrival = None, None
    duration = number(row.get('duration_minutes'))
    dep = row.get('departure_time')
    arr = row.get('arrival_time')
    if isinstance(dep, str) and re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', dep):
        departure = datetime.fromisoformat(request.date.isoformat() + 'T' + dep).replace(tzinfo=INDIA)
        if duration is not None:
            derived = departure + timedelta(minutes=duration)
            if isinstance(arr, str) and derived.strftime('%H:%M') == arr:
                arrival = derived.isoformat()
    summaries = [{'class_code': str(s.get('class_code') or ''), 'status': str(s.get('status') or 'UNKNOWN'),
                  'text': str(s.get('text') or '')[:200], 'fare': number(s.get('fare')),
                  'updated_at': iso(s.get('last_updated_at'))} for s in row.get('availability_summary', [])[:10]]
    prices = [s['fare'] for s in summaries if s['fare'] is not None]
    return {'id': train, 'name': str(row.get('extended_train_name') or row.get('train_name') or train)[:200],
            'service_number': train, 'origin_code': row['from_station_code'],
            'destination_code': row['to_station_code'],
            'origin_name': row.get('from_station_name'), 'destination_name': row.get('to_station_name'),
            'departure': departure.isoformat() if departure else None, 'arrival': arrival,
            'arrival_time': arr, 'duration_minutes': duration, 'price': min(prices) if prices else None,
            'currency': 'INR', 'data_kind': 'provider_schedule',
            'classes': [c for c in row.get('classes', [])[:10] if isinstance(c, str) and re.fullmatch(r'[A-Z0-9]{1,3}', c)],
            'availability_summary': summaries, 'booking_url': 'https://www.irctc.co.in/'}


async def search_trains(request, output, get):
    output['provider'] = 'RailCore'
    options = await asyncio.gather(station_options(request.origin, get), station_options(request.destination, get))
    output['origin_points'], output['destination_points'] = options
    origin = request.origin_code or choose_station(options[0])
    destination = request.destination_code or choose_station(options[1])
    output.update(origin_code=origin, destination_code=destination)
    if not origin or not destination:
        output.update(status='choose_points', notice='Choose the boarding and arrival stations. No station has been guessed.')
        return output
    if origin == destination:
        output.update(notice='The selected stations are the same. Choose different boarding and arrival stations.')
        return output
    body = await get('railcore', RAIL + '/routes/trains', {'from': origin, 'to': destination,
                     'date': request.date.isoformat(), 'quota': 'GN', 'match': 'city'})
    data = body.get('data', {})
    if data.get('journey_date') != request.date.isoformat():
        raise ProviderIssue('provider_error', 'The provider did not confirm the requested journey date. No services are displayed.')
    used = request.model_copy(update={'origin_code': origin, 'destination_code': destination})
    output['offers'] = [o for row in data.get('trains', [])[:30] if (o := train_offer(row, used))]
    output.update(status='results' if output['offers'] else 'no_results',
                  notice='Provider schedules for your date. Class summaries may be old; use Check seats for a new enquiry. '
                         'Nearby city stations may differ from your selected stations. Confirm transfers and boarding points.'
                         if output['offers'] else 'No route-matching trains were returned. This does not rule out connections or other stations.')
    return output


async def search_flights(request, output, get):
    output['provider'] = 'Aviasales / Travelpayouts'
    options = await asyncio.gather(airport_options(request.origin_code or request.origin, get),
                                   airport_options(request.destination_code or request.destination, get))
    output['origin_points'], output['destination_points'] = options
    def choose(points, selected):
        matches = [p for p in points if p['code'] == selected] if selected else [p for p in points if p['exact']]
        return matches[0]['code'] if len(matches) == 1 else None
    origin, destination = choose(options[0], request.origin_code), choose(options[1], request.destination_code)
    output.update(origin_code=origin, destination_code=destination)
    if not origin or not destination:
        missing = [name for name, points in zip((request.origin, request.destination), options) if not points]
        notice = ('The flight provider airport directory has no Indian match for ' + ', '.join(missing) + '. '
                  'Choose another departure/arrival airport below, or use the external flight search links. '
                  if missing else 'Choose the departure and arrival airport codes below. ')
        output.update(status='choose_points', notice=notice + 'Airport transfers are not included; no flight fare search has been made yet.')
        return output
    if origin == destination:
        output.update(notice='The selected airport/city codes are the same. No flight search is needed.')
        return output
    body = await get('aviasales', FLIGHTS, {'origin': origin, 'destination': destination,
        'departure_at': request.date.isoformat(), 'one_way': 'true', 'currency': 'inr', 'sorting': 'price',
        'unique': 'false', 'limit': 10, 'page': 1})
    for row in body.get('data', [])[:10] if isinstance(body.get('data'), list) else []:
        departure = iso(row.get('departure_at'))
        if not departure or datetime.fromisoformat(departure).astimezone(INDIA).date() != request.date:
            continue
        if row.get('origin') != origin or row.get('destination') != destination:
            continue
        if row.get('currency') and str(row['currency']).upper() != 'INR':
            continue
        if iso(row.get('expires_at')) and datetime.fromisoformat(iso(row['expires_at'])) <= datetime.now(timezone.utc):
            continue
        duration = number(row.get('duration_to'))
        link = row.get('link') or ''
        link = 'https://www.aviasales.com' + link if isinstance(link, str) and link.startswith('/search/') else link
        parsed = urlparse(link) if isinstance(link, str) else None
        if not parsed or parsed.scheme != 'https' or parsed.hostname not in {'www.aviasales.com', 'aviasales.com'} or parsed.username:
            link = 'https://www.aviasales.com/'
        airline = str(row.get('airline') or '')[:8]
        flight = str(row.get('flight_number') or '')[:12]
        output['offers'].append({'id': f'{airline}-{flight}-{departure}', 'name': f'{airline} {flight}'.strip() or 'Reported flight fare',
            'service_number': f'{airline} {flight}'.strip(), 'origin_code': row.get('origin_airport') or origin,
            'destination_code': row.get('destination_airport') or destination, 'departure': departure,
            'arrival': (datetime.fromisoformat(departure) + timedelta(minutes=duration)).isoformat() if duration is not None else None,
            'duration_minutes': duration, 'price': number(row.get('price')), 'currency': 'INR',
            'data_kind': 'cached_fare', 'transfers': number(row.get('transfers')), 'booking_url': link,
            'found_at': iso(row.get('found_at')), 'classes': [], 'availability_summary': []})
    output.update(status='results' if output['offers'] else 'no_results',
        notice='Recently found fares, not a complete flight timetable or confirmed seat availability. '
               'The one-way cache may return only one offer. Confirm fares, airport transfers and availability on the booking site.'
               if output['offers'] else 'No cached fares matched this date and route. This does not mean no flights operate; check the live search links.')
    return output


async def search_transport(request, get=None):
    get = get or provider_get
    output = result_base(request)
    settings = get_settings()
    if request.mode == 'bus':
        output.update(status='external_search', notice='Live bus inventory is not connected to a verified free API. '
                      'Use the links to check operators, departure times, fares and seats for your date. No bus service is assumed available.')
        return output
    if settings.app_mode != 'live':
        output.update(status='demo', notice='Demo mode: no live transport search was made. Use the links to check real services.')
        return output
    key = settings.railcore_api_key if request.mode == 'train' else settings.travelpayouts_api_token
    if not key:
        output.update(status='not_connected', notice=('Train search is not connected yet. Check railway services using the links below.'
                     if request.mode == 'train' else 'Flight fare search is not connected yet. Check current flights using the links below.'))
        return output
    try:
        async with asyncio.timeout(25):
            return await (search_trains(request, output, get) if request.mode == 'train' else search_flights(request, output, get))
    except ProviderIssue as error:
        output.update(status=error.code, notice=error.message)
    except (TimeoutError, TypeError, ValueError, KeyError, AttributeError):
        output.update(status='provider_error', notice='Transport results could not be verified. Please retry or use the external links.')
    return output


@router.post('/search')
async def search(request: SearchRequest):
    return await search_transport(request)


@router.post('/train-availability')
async def availability(request: SeatRequest):
    result = {'status': 'not_connected', 'classes': [], 'retrieved_at': utc_now(), 'provider': 'RailCore',
              'notice': 'Train availability is not connected yet. Please confirm seats with IRCTC.'}
    settings = get_settings()
    if settings.app_mode != 'live' or not settings.railcore_api_key:
        return result
    try:
        body = await provider_get('railcore', RAIL + '/availability/seats', {'train_number': request.train_number,
            'from': request.origin_code, 'to': request.destination_code, 'date': request.date.isoformat(),
            'class': request.travel_class, 'quota': 'GN'})
        data = body.get('data', {})
        if (str(data.get('train_number')) != request.train_number or data.get('journey_date') != request.date.isoformat()
                or data.get('from_station_code') != request.origin_code or data.get('to_station_code') != request.destination_code):
            raise ValueError('Mismatched availability enquiry')
        rows = [c for c in data.get('classes', []) if c.get('class_code') == request.travel_class]
        result.update(status='results' if rows else 'no_results', classes=[{
            'class_code': c['class_code'], 'status': str(c.get('status') or 'UNKNOWN'),
            'text': str(c.get('availability_text') or 'Not supplied')[:200], 'available_count': number(c.get('available_count')),
            'fare': number(c.get('total_fare')), 'updated_at': iso(c.get('last_updated_at'))} for c in rows],
            notice='New provider enquiry. Source data may have been read earlier; check its timestamp. '
                   'Reported availability can change and does not reserve seats.')
    except ProviderIssue as error:
        result.update(status=error.code, notice=error.message)
    except (TypeError, ValueError, KeyError, AttributeError):
        result.update(status='provider_error', notice='The returned availability could not be verified. Please check with IRCTC.')
    return result
