"""Deterministic meal windows, sourced places and optional road overnight reviews.

No model supplies venue names, ratings, coordinates, or booking claims here.
All route clocks are estimates, not traffic forecasts or public timetables.
"""
import asyncio
import copy
import math
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlencode, urlparse

from pydantic import BaseModel, Field, field_validator

from app.config import get_settings
from app.geoapify import FreeQuotaExceeded, geoapify_fetch
from app.places import coordinates
from app.planning import clock_minutes


MEALS = [('Breakfast', '08:00', '09:00'), ('Lunch', '13:00', '14:00'), ('Dinner', '20:00', '21:00')]
GEOCODE = 'https://api.geoapify.com/v1/geocode/search'
ROUTING = 'https://api.geoapify.com/v1/routing'
PLACES = 'https://api.geoapify.com/v2/places'


class ServicePreferences(BaseModel):
    transport_mode: Literal['unspecified', 'car/taxi', 'train', 'bus', 'flight'] = 'unspecified'
    departure_time: str | None = None
    return_departure_time: str | None = None
    dietary: Literal['any', 'vegetarian', 'vegan'] = 'any'
    cuisine: str = Field(default='', max_length=100)
    accessibility: bool = False
    stay_preference: Literal['any', 'hotel', 'guest_house', 'hostel', 'apartment'] = 'any'

    @field_validator('departure_time', 'return_departure_time')
    @classmethod
    def clock(cls, value):
        if value is not None:
            clock_minutes(value)
        return value


class StopChoice(BaseModel):
    day: int = Field(ge=1, le=7)
    place_id: str = Field(min_length=1, max_length=500)
    leg: Literal['outbound', 'return'] = 'outbound'


def hhmm(minutes):
    return f'{int(minutes) // 60 % 24:02d}:{int(minutes) % 60:02d}'


def stamp(day_date, minutes):
    return (datetime.combine(day_date, datetime.min.time()) + timedelta(minutes=minutes)).isoformat(timespec='minutes') + '+05:30'


def distance(a, b):
    """Metres between [longitude, latitude] positions (never a road detour)."""
    lat1, lat2 = map(math.radians, (a[1], b[1]))
    dlat, dlon = lat2 - lat1, math.radians(b[0] - a[0])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(h)))


def safe_url(value):
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    return value if parsed.scheme in {'http', 'https'} and parsed.hostname and not parsed.username else None


def search_link(place, kind):
    return 'https://www.google.com/maps/search/?' + urlencode({'api': 1, 'query': f'{kind} near {place}'})


def simple_hours_overlap(hours, window):
    """Exclude clearly closed venues for simple daily listings only.

    Full OSM hours can include holidays, seasons and exceptions. Those stay
    unknown rather than being interpreted as verified date-specific hours.
    """
    if not hours or not window:
        return None
    value = hours.strip()
    if value == '24/7':
        return True
    value = re.sub(r'^Mo-Su\s+', '', value)
    if not re.fullmatch(r'\d{2}:\d{2}-\d{2}:\d{2}(?:\s*,\s*\d{2}:\d{2}-\d{2}:\d{2})*', value):
        return None
    intervals = []
    try:
        for interval in value.split(','):
            left, right = interval.strip().split('-')
            left = clock_minutes(left)
            right = 1440 if right == '24:00' else clock_minutes(right)
            intervals.extend([(left, right)] if right > left else [(left, 1440), (0, right)])
    except ValueError:
        return None
    start, end = map(clock_minutes, window)
    return any(max(start, left) < min(end, right) for left, right in intervals)


def reserve_meals(result, request):
    """Reflow activities around the three fixed windows without shortening visits.

    An overfull day becomes an honest draft with unscheduled candidates. Meals
    outside sightseeing hours do not extend the sightseeing window.
    """
    for day in result['schedule']:
        day['meal_windows'] = [{'meal': name, 'start': start, 'end': end} for name, start, end in MEALS]
        if day['status'] != 'scheduled':
            continue
        original = [a for a in day['activities'] if a['kind'] != 'meal']
        def layout(activities):
            slots, cursor = [], clock_minutes(request['day_start'])
            for activity in activities:
                duration = activity['duration_minutes']
                for _, begin, finish in MEALS:
                    left, right = clock_minutes(begin), clock_minutes(finish)
                    if cursor < right + 15 and cursor + duration > left - 15:
                        cursor = right + 15
                slots.append({**activity, 'start': hhmm(cursor), 'end': hhmm(cursor + duration)})
                cursor += duration
            return slots, cursor
        original = copy.deepcopy(original)
        slots, cursor = layout(original)
        # Flexible rest can make room for meal access; visits and transfers keep
        # their full duration. Recompute because moving a meal changes gaps.
        for activity in reversed(original):
            deficit = cursor - clock_minutes(request['day_end'])
            if deficit <= 0:
                break
            if activity['kind'] == 'break':
                activity['duration_minutes'] = max(0, activity['duration_minutes'] - deficit)
                if activity['duration_minutes'] < 5:
                    activity['duration_minutes'] = 0
                slots, cursor = layout([a for a in original if a['duration_minutes']])
        original = [a for a in original if a['duration_minutes']]
        if cursor > clock_minutes(request['day_end']):
            day.update(status='needs_review', activities=[], unscheduled_options=original,
                       review_note='Visits, transfers and meal/access allowances do not fit the sightseeing window. '
                       'Choose fewer activities; durations have not been shortened.')
            result['planning_status'] = 'needs_review'
        else:
            day['activities'] = slots
    return result


class Lookup:
    """Per-plan deduplication and a strict request budget; no persistent venue cache."""
    def __init__(self, key, fetch=None):
        self.key, self.fetch = key, fetch or geoapify_fetch
        self.cache, self.calls = {}, 0
        self.blocked = None
        self.deadline = time.monotonic() + 40

    async def get(self, url, params):
        if self.blocked:
            raise FreeQuotaExceeded(self.blocked)
        marker = (url, tuple(sorted(params.items())))
        if marker in self.cache:
            return self.cache[marker]
        if self.calls >= 75:
            raise FreeQuotaExceeded('The per-plan free lookup allowance was reached. Refine one day at a time.')
        self.calls += 1
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            self.blocked = 'The free lookup time budget was reached. Some suggestions are unavailable; try again later.'
            raise FreeQuotaExceeded(self.blocked)
        try:
            async with asyncio.timeout(min(8, remaining)):
                data = await self.fetch(url, {**params, 'apiKey': self.key})
        except FreeQuotaExceeded as error:
            self.blocked = str(error)
            raise
        except (TimeoutError, OSError):
            self.blocked = 'The free place/route provider is unavailable. Retry later.'
            raise
        self.cache[marker] = data
        return data

    async def town(self, name, state=None):
        # Scope regional bases to their state; never use a state centroid.
        text = name if ',' in name or not state else f'{name}, {state}'
        data = await self.get(GEOCODE, {'text': text, 'type': 'city', 'filter': 'countrycode:in', 'limit': 5})
        candidates = []
        aliases = {'mysore': 'mysuru', 'cochin': 'kochi', 'alleppey': 'alappuzha', 'panjim': 'panaji'}
        def norm(value):
            value = value.strip().casefold()
            return aliases.get(value, value)
        first = norm(name.split(',')[0])
        for feature in data.get('features', []):
            p = feature.get('properties', {})
            names = {norm(str(p.get(k, ''))) for k in ('city', 'name', 'town', 'village')}
            if p.get('country_code', '').lower() != 'in' or first not in names:
                continue
            hints = [v.strip().casefold() for v in name.split(',')[1:] if v.strip()]
            allowed = {str(p.get(k, '')).casefold() for k in ('state', 'county', 'country', 'country_code')}
            if state:
                hints.append(state.casefold())
            if any(h not in allowed for h in hints):
                continue
            point = feature.get('geometry', {}).get('coordinates', [])
            lat, lon = coordinates(p.get('lat', point[1] if len(point) > 1 else None),
                                   p.get('lon', point[0] if point else None))
            if not any(distance([lon, lat], c) < 1000 for c in candidates):
                candidates.append([lon, lat])
        if len(candidates) != 1:
            raise ValueError('A unique town could not be verified. Use city, state, India.')
        return candidates[0]

    async def route(self, start, end):
        data = await self.get(ROUTING, {'waypoints': f'{start[1]},{start[0]}|{end[1]},{end[0]}',
                                      'mode': 'drive', 'type': 'balanced'})
        feature = next(iter(data.get('features', [])), None)
        if not feature or not feature.get('properties', {}).get('time'):
            raise ValueError('No drivable route was returned.')
        return feature

    async def places(self, point, kind, prefs, radius=3000, window=None):
        category = ('accommodation' + ('.' + prefs.stay_preference if prefs.stay_preference != 'any' else '')
                    if kind == 'stay' else 'catering.restaurant,catering.cafe')
        lon, lat = point
        params = {'categories': category, 'filter': f'circle:{lon},{lat},{radius}',
                  'bias': f'proximity:{lon},{lat}', 'limit': 20}
        conditions = []
        if prefs.accessibility:
            conditions.append('wheelchair')
        if kind == 'meal' and prefs.dietary != 'any':
            conditions.append('vegan' if prefs.dietary == 'vegan' else 'vegetarian')
        if conditions:
            params['conditions'] = ','.join(conditions)
        data = await self.get(PLACES, params)
        output, seen = [], set()
        for feature in data.get('features', [])[:20]:
            p = feature.get('properties', {})
            if not p.get('name') or not p.get('place_id') or p['place_id'] in seen:
                continue
            xy = feature.get('geometry', {}).get('coordinates', [])
            if len(xy) < 2:
                continue
            try:
                latitude, longitude = coordinates(xy[1], xy[0])
            except (TypeError, ValueError):
                continue
            raw = (p.get('datasource') or {}).get('raw') or {}
            if kind == 'meal' and simple_hours_overlap(raw.get('opening_hours'), window) is False:
                continue
            cuisine = str(raw.get('cuisine') or '')[:160]
            if kind == 'meal' and prefs.cuisine and prefs.cuisine.casefold() not in cuisine.casefold():
                continue
            seen.add(p['place_id'])
            output.append({'id': p['place_id'], 'name': str(p['name'])[:200], 'point': [longitude, latitude],
                'address': str(p.get('formatted') or '')[:500], 'type': ', '.join(p.get('categories', []))[:300],
                'distance_m': round(distance(point, [longitude, latitude])),
                'url': f'https://www.openstreetmap.org/?mlat={latitude}&mlon={longitude}#map=17/{latitude}/{longitude}',
                'website': safe_url(p.get('website') or (p.get('contact') or {}).get('website') or raw.get('website')),
                'phone': str((p.get('contact') or {}).get('phone') or raw.get('phone') or '')[:80] or None,
                'opening_hours': str(raw.get('opening_hours') or '')[:300] or None,
                'cuisine': cuisine or None,
                'amenities': [label for key, label in [('internet_access', 'Internet listed'),
                    ('wheelchair', 'Wheelchair access listed'), ('parking', 'Parking listed')]
                    if str(raw.get(key, '')).lower() in {'yes', 'wlan', 'wifi', 'designated'}],
                'quality_note': 'Location and listed amenities match; ratings, room prices and availability are not verified.',
                'reason': 'Near the planned stop; confirm access, suitability and opening/check-in times.',
                'provider': 'Geoapify / OpenStreetMap', 'retrieved_at': datetime.now(timezone.utc).isoformat()})
        return sorted(output, key=lambda p: (-len(p['amenities']), p['distance_m']))[:3]


def route_point(route, elapsed_minutes):
    """Approximate position using provider step durations and route geometry."""
    geometry = route.get('geometry', {})
    lines = geometry.get('coordinates', [])
    if geometry.get('type') == 'LineString':
        lines = [lines]
    remaining = max(0, elapsed_minutes * 60)
    for index, leg in enumerate(route['properties'].get('legs', [])):
        line = lines[index] if index < len(lines) else []
        for step in leg.get('steps', []):
            seconds = step.get('time', 0)
            if remaining <= seconds and seconds > 0 and line:
                left, right = int(step['from_index']), int(step['to_index'])
                # Stay on a returned geometry vertex; do not interpolate a
                # straight line between distant endpoints across non-road land.
                return line[min(len(line) - 1, max(0, round(left + (right - left) * remaining / seconds)))]
            remaining -= seconds
    if lines and lines[-1] and elapsed_minutes * 60 >= route['properties']['time']:
        return lines[-1][-1]
    raise ValueError('Route timing geometry is incomplete; no intermediate location guessed.')


def road_clock(route, departure):
    """Reserve fixed meals and 15-minute access buffers during long road travel."""
    total = math.ceil(route['properties']['time'] / 60)
    cursor, driven, pauses = departure, 0, []
    # Multi-day journeys need an overnight review, never an uninterrupted
    # driving recommendation. Only today's segment is used for place searches.
    for name, begin, end in MEALS:
        left, right = clock_minutes(begin), clock_minutes(end)
        if departure >= right:
            continue
        if cursor < right and cursor + total - driven > left - 15:
            drive = max(0, left - 15 - cursor)
            driven += drive
            pauses.append({'meal': name, 'from': left - 15, 'until': right + 15,
                           'drive_minutes': min(driven, total)})
            cursor = right + 15
    return cursor + total - driven, pauses


def elapsed_driving(at, departure, pauses):
    elapsed = max(0, at - departure)
    for pause in pauses:
        elapsed -= max(0, min(at, pause['until']) - max(departure, pause['from']))
    return max(0, elapsed)


async def build_services(result, request, preferences=None, *, fetch=None, lookup=None, returning=False):
    prefs = preferences or ServicePreferences.model_validate(request)
    settings = get_settings()
    lookup = lookup or Lookup(settings.geoapify_api_key, fetch)
    enabled = settings.app_mode == 'live' and bool(settings.geoapify_api_key)
    reason = ('Demo mode: no live restaurant or accommodation lookup was made.' if settings.app_mode != 'live'
              else 'Place suggestions need a free Geoapify API key in backend/.env.' if not settings.geoapify_api_key else None)
    output = {'preferences': prefs.model_dump(), 'days': [], 'provider': 'Geoapify / OpenStreetMap',
              'notice': reason, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
              'limitations': 'References only. Future opening hours, ratings, room prices, availability and late check-in are unverified. '
              'Driving times exclude traffic and are estimates. Free lookup quotas are shared with attraction searches.'}
    state = result.get('research', {}).get('tourism_route', {}).get('state') or result.get('research', {}).get('location', {}).get('admin1')
    days = result['schedule']
    previous = request.get('origin')
    for entry in days:
        base, number = entry['base'], entry['day']
        day_date = date.fromisoformat(entry['date'])
        item = {'day': number, 'date': entry['date'], 'base': base, 'meals': [],
                'destination_stays': [], 'stay_notice': reason, 'overnight': {'status': 'not_required', 'places': []}}
        departure = clock_minutes(prefs.departure_time) if prefs.departure_time else None
        route, arrival, pauses, point = None, None, [], None
        # One-day return trips have two journeys and require a separate timing
        # review. Do not manufacture a second departure time.
        source = previous
        target = base
        same_base = bool(source and source.split(',')[0].strip().casefold() == base.split(',')[0].strip().casefold())
        if enabled:
            try:
                point = await lookup.town(base, state)
                item['destination_stays'] = await lookup.places(point, 'stay', prefs, radius=5000)
                item['stay_notice'] = (None if item['destination_stays'] else 'No matching stays returned. Try a different accommodation type or area.')
            except Exception as error:
                item['stay_notice'] = public_lookup_error(error)
            if not same_base and source:
                item['overnight'] = {'status': 'timing_unknown', 'places': [],
                    'reason': 'Select car/taxi and a road departure time to check travel after 22:00. '
                              'For scheduled transport, verify arrival and accessible stops with the operator.'}
                if point and prefs.transport_mode == 'car/taxi' and departure is not None:
                    try:
                        origin_point = await lookup.town(source, state if number > 1 else None)
                        route = await lookup.route(origin_point, point)
                        arrival, pauses = road_clock(route, departure)
                        item['journey'] = {'origin': source, 'destination': base,
                            'start_point': origin_point, 'end_point': point,
                            'departure': stamp(day_date, departure), 'arrival': stamp(day_date, arrival),
                            'duration_minutes': math.ceil(route['properties']['time'] / 60),
                            'distance_km': round(route['properties'].get('distance', 0) / 1000, 1),
                            'timing_basis': 'Provider driving estimate plus meals/access allowances; no live traffic.',
                            'route_url': 'https://www.google.com/maps/dir/?' + urlencode({'api': 1, 'origin': source, 'destination': base})}
                        item['overnight'] = {'status': 'not_required', 'places': [], 'reason': 'Estimated travel ends at or before 22:00.'}
                        if arrival > 22 * 60:
                            item['overnight'] = {'status': 'suggested', 'places': [],
                                'reason': 'Estimated travel continues past 22:00. Review an overnight stop before changing your journey.'}
                            cutoff = max(departure, 21 * 60)
                            anchor = route_point(route, elapsed_driving(cutoff, departure, pauses))
                            candidates = await lookup.places(anchor, 'stay', prefs, radius=8000)
                            # Verify road access, arrival and detour independently
                            # for every candidate; proximity alone is insufficient.
                            for candidate in candidates:
                                try:
                                    first = await lookup.route(origin_point, candidate['point'])
                                    onward = await lookup.route(candidate['point'], point)
                                    stop_arrival, _ = road_clock(first, departure)
                                    if stop_arrival > 22 * 60:
                                        continue
                                    candidate.update(arrival=stamp(day_date, stop_arrival),
                                        detour_minutes=max(0, math.ceil((first['properties']['time'] + onward['properties']['time'] - route['properties']['time']) / 60)),
                                        onward_minutes=math.ceil(onward['properties']['time'] / 60),
                                        reason='Road access checked against this journey; estimated arrival before 22:00. Confirm late check-in.')
                                    item['overnight']['places'].append(candidate)
                                except Exception:
                                    continue
                            if not item['overnight']['places']:
                                item['overnight']['reason'] += ' No reachable accommodation before the cutoff could be verified; depart earlier or review the route.'
                    except Exception as error:
                        item['overnight'] = {'status': 'timing_unknown', 'places': [], 'reason': public_lookup_error(error)}
        elif not same_base:
            item['overnight'] = {'status': 'timing_unknown', 'places': [], 'reason': reason}
        for name, begin, finish in MEALS:
            meal = {'meal': name, 'start': begin, 'end': finish, 'location': base, 'places': [],
                    'notice': reason, 'status': 'suggested', 'search_url': search_link(base, name + ' restaurants')}
            anchor = point
            if same_base and point and name == 'Lunch' and entry['status'] == 'scheduled':
                visits = [a for a in entry['activities'] if a['kind'] == 'visit' and a['end'] <= begin]
                if visits:
                    title = visits[-1]['title'].casefold()
                    known_places = [p for e in result.get('research', {}).get('evidence', [])
                                    for p in e.get('data', {}).get('places', [])]
                    found = next((p for p in known_places if p.get('name', '').casefold() == title
                                  and p.get('latitude') is not None and p.get('longitude') is not None), None)
                    if found:
                        try:
                            lat, lon = coordinates(found['latitude'], found['longitude'])
                            if distance(point, [lon, lat]) <= 50000:
                                anchor = [lon, lat]
                                meal['location'] = found['name'] + ', ' + base
                        except (TypeError, ValueError):
                            pass
            if not same_base and not route:
                meal.update(status='needs_review', notice=reason or
                    'Journey timing is unverified. These are base-area alternatives, not confirmed accessible stops during travel.')
            if entry['status'] == 'needs_review':
                meal['status'] = 'needs_review'
                meal['notice'] = meal['notice'] or 'Day timing needs review; confirm your location before choosing a restaurant.'
            if route and departure is not None:
                window = clock_minutes(begin)
                if departure < window + 60 and arrival > window:
                    try:
                        pause = next((p for p in pauses if p['meal'] == name), None)
                        if departure > window - 15 or not pause:
                            raise ValueError('Departure overlaps this meal window. Eat before departure or adjust the journey.')
                        anchor = route_point(route, pause['drive_minutes'])
                        meal['location'] = f'Along {source} to {base}'
                        meal['notice'] = 'Roadside candidates near an estimated meal stop. Confirm road access and hours; allow 15 minutes each way.'
                    except ValueError as error:
                        anchor = None
                        meal.update(status='needs_review', notice=str(error))
                elif window + 60 <= departure:
                    anchor = item['journey']['start_point']
                    meal['location'] = source
                elif arrival <= window:
                    anchor = point
            if enabled and anchor:
                try:
                    meal['places'] = await lookup.places(anchor, 'meal', prefs, window=(begin, finish))
                    if route and meal['location'].startswith('Along '):
                        accessible = []
                        for candidate in meal['places']:
                            try:
                                to_place = await lookup.route(anchor, candidate['point'])
                                back = await lookup.route(candidate['point'], anchor)
                                out_minutes = math.ceil(to_place['properties']['time'] / 60)
                                back_minutes = math.ceil(back['properties']['time'] / 60)
                                if out_minutes <= 15 and back_minutes <= 15:
                                    candidate['detour_minutes'] = out_minutes + back_minutes
                                    candidate['reason'] = 'Road access checked from the estimated meal stop; within the 15-minute access allowance each way. Confirm opening hours.'
                                    accessible.append(candidate)
                            except Exception:
                                continue
                        meal['places'] = accessible
                    if not meal['places']:
                        meal['notice'] = 'No matching food places returned. Check the map or relax cuisine/diet filters; suitability is not inferred.'
                except Exception as error:
                    meal['notice'] = public_lookup_error(error)
            meal['search_url'] = search_link(meal['location'] if not meal['location'].startswith('Along ') else base, name + ' restaurants')
            item['meals'].append(meal)
        if entry is days[-1] and not returning:
            item['return_notice'] = 'Return departure/arrival timing needs separate confirmation. Destination meal and stay references do not confirm where you will be during the return journey.'
            if prefs.transport_mode == 'car/taxi' and prefs.return_departure_time and request.get('origin'):
                # Reuse the same bounded lookup/cache for the final journey home.
                home_day = copy.deepcopy(entry)
                home_day['base'] = request['origin']
                home_result = {**result, 'research': {}, 'schedule': [home_day]}
                home_request = {**request, 'origin': base}
                home_prefs = prefs.model_copy(update={'departure_time': prefs.return_departure_time})
                returned = await build_services(home_result, home_request, home_prefs,
                                                lookup=lookup, returning=True)
                home = returned['days'][0]
                item['return_journey'] = home
                item['return_notice'] = 'Return road estimates use your separate return departure. Destination stays remain optional references; no reservation is assumed.'
                return_start = clock_minutes(prefs.return_departure_time)
                for index, meal in enumerate(item['meals']):
                    if clock_minutes(meal['end']) > return_start:
                        item['meals'][index] = home['meals'][index]
                if home.get('journey'):
                    reconcile_travel(entry, home['journey'])
                    if item.get('journey') and item['journey']['arrival'] > home['journey']['departure']:
                        item['return_notice'] = 'Conflict: the return departure precedes estimated outward arrival. Change departure times or trip duration. These journeys are not a feasible schedule.'
                        entry['status'] = 'needs_review'
                        entry['review_note'] = item['return_notice']
        item['stay_search_url'] = search_link(base, 'accommodation')
        if prefs.transport_mode == 'car/taxi' and departure is not None and item.get('journey'):
            reconcile_travel(entry, item['journey'])
        output['days'].append(item)
        previous = base
    # Do not claim that the traveller has reached a base while a previous day's
    # long journey is still in progress. Multi-day transport needs a new review.
    for index, day in enumerate(output['days']):
        for prior in output['days'][:index]:
            journey = prior.get('journey')
            if not journey or journey['arrival'][:10] < day['date']:
                continue
            reconcile_travel(days[index], journey)
            for meal in day['meals']:
                if stamp(date.fromisoformat(day['date']), clock_minutes(meal['start'])) < journey['arrival']:
                    meal.update(status='needs_review', places=[], notice='A prior journey is still in progress at this meal time. '
                                'Review an overnight stop and onward timing; no destination restaurant is assumed accessible.')
    return output


def public_lookup_error(error):
    if isinstance(error, FreeQuotaExceeded):
        return str(error)
    if isinstance(error, ValueError):
        return 'Location or road access could not be verified. Use a specific city and state, or check the map.'
    return 'The free place/route provider is unavailable. References can be checked on the map; retry later.'


def reconcile_travel(entry, journey):
    if not entry['activities']:
        return
    arrival = datetime.fromisoformat(journey['arrival'])
    departure = datetime.fromisoformat(journey['departure'])
    # Reserve travel plus check-in/access before preserving any sightseeing.
    conflict = any(datetime.fromisoformat(entry['date'] + 'T' + a['start'] + '+05:30') < arrival + timedelta(minutes=30)
                   and datetime.fromisoformat(entry['date'] + 'T' + a['end'] + '+05:30') > departure
                   for a in entry['activities'])
    if conflict:
        entry.update(status='needs_review', unscheduled_options=entry['activities'], activities=[],
                     review_note='Estimated road travel and arrival/check-in overlap these activities. '
                     'They are unscheduled until you revise travel timing or choose fewer visits.')


def stop_review(services, choice):
    """A review proposal only: no booking, date change, or schedule mutation."""
    day = next((d for d in services['days'] if d['day'] == choice.day), None)
    if day and choice.leg == 'return':
        day = day.get('return_journey')
    if not day or day['overnight']['status'] != 'suggested':
        raise ValueError('No overnight alternatives are available for this day.')
    place = next((p for p in day['overnight']['places'] if p['id'] == choice.place_id), None)
    if not place:
        raise ValueError('Choose an accommodation returned for this route.')
    following = date.fromisoformat(day['date']) + timedelta(days=1)
    onward = place['onward_minutes']
    # Leave after breakfast, with a check-out/access allowance. Further meal
    # stops are conservatively added when crossing their windows.
    arrival = 9 * 60 + 30 + onward
    if arrival > 13 * 60 - 15:
        arrival += 90
    if arrival > 20 * 60 - 15:
        arrival += 90
    end = date.fromisoformat(services['days'][-1]['date'])
    return {'day': choice.day, 'place': place['name'], 'arrival': place['arrival'],
            'onward_departure': stamp(following, 9 * 60 + 30), 'onward_arrival': stamp(following, arrival),
            'detour_minutes': place['detour_minutes'], 'affected_days': [choice.day, choice.day + 1],
            'extends_trip': following + timedelta(days=arrival // 1440) > end,
            'status': 'needs_review', 'notice': 'Alternative only; your itinerary and dates have not changed. '
            'Breakfast 08:00–09:00, then provisional checkout and departure at 09:30. '
            'Onward arrival includes provisional meal/access allowances. Confirm the property, then revise '
            'affected travel and sightseeing days in chat before following this alternative. No reservation was made.'}


def append_service_text(result, services):
    """Include meals/references in saved/export previews as well as the UI."""
    text = result['answer']
    begin, end = text.find('\nDay 1:'), text.find('\nSuggested budget allocation:')
    if begin >= 0 and end > begin:
        blocks = []
        for entry in result['schedule']:
            blocks += ['', f"Day {entry['day']}: {entry['date']} — {entry['base']}"]
            if entry.get('weather'):
                from app.weather import weather_text
                blocks.append(weather_text(entry['weather']))
            if entry['status'] == 'needs_review':
                blocks.append('Needs review: ' + entry.get('review_note', 'Confirm travel timing.'))
                blocks.extend(f"- Optional, unscheduled: {a['title']} — {a['duration_minutes']} min (estimate)."
                              for a in entry.get('unscheduled_options', []))
            else:
                blocks.extend(f"- {a['start']}–{a['end']} | {a['title']} | {a['duration_minutes']} min (estimate). {a['description']}"
                              for a in entry['activities'])
        result['answer'] = text[:begin] + '\n'.join(blocks) + '\n' + text[end:]
    lines = ['','Food and accommodation:', services['limitations']]
    for day in services['days']:
        lines += ['', f"Day {day['day']} food and stays — {day['base']}"]
        for meal in day['meals']:
            names = '; '.join(p['name'] for p in meal['places'])
            lines.append(f"- {meal['start']}–{meal['end']} {meal['meal']}: {meal['location']}. " + (names or meal['notice'] or 'Check local options.'))
        names = '; '.join(p['name'] for p in day['destination_stays'])
        lines.append('- Destination accommodation: ' + (names or day['stay_notice'] or 'No matching stays found.'))
        night = day['overnight']
        if night['status'] != 'not_required':
            lines.append('- Overnight route check: ' + night.get('reason', ''))
            lines.extend('- Route accommodation: ' + p['name'] + ' — confirm late check-in.' for p in night['places'])
        if day.get('return_journey'):
            home = day['return_journey']
            if home.get('journey'):
                lines.append('- Return journey: estimated arrival ' + home['journey']['arrival'])
            if home['overnight']['status'] != 'not_required':
                lines.append('- Return overnight check: ' + home['overnight'].get('reason', ''))
                lines.extend('- Return route accommodation: ' + p['name'] for p in home['overnight']['places'])
    result['answer'] += '\n'.join(lines)
    result['food_stays'] = services
    if any(d['status'] == 'needs_review' for d in result['schedule']):
        result['planning_status'] = 'needs_review'
        if not result['answer'].startswith('Draft itinerary'):
            result['answer'] = 'Draft itinerary — review meal/travel timing before following this plan.\n\n' + result['answer']
    return result
