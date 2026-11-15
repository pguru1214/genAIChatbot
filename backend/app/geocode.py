"""Best-effort coordinates for drawing the trip route in the browser.

Uses the free, key-less Open-Meteo geocoder restricted to India. Results are
cached in-process. A failed or doubtful lookup returns ``None`` so the UI can
fall back to a schematic route; nothing here affects planning decisions.
"""
import asyncio
import math
import re

from app.config import get_settings
from app.tools import fetch

GEOCODER = 'https://geocoding-api.open-meteo.com/v1/search'
NEAR_KM = 350
_cache: dict[tuple, dict | None] = {}
_IGNORED_HINTS = {'india', 'in', 'bharat'}
# Provider canonical names (same aliases the destination resolver uses).
_ALIASES = {'panaji': 'Panjim', 'margao': 'Madgaon', 'mysuru': 'Mysore', 'cochin': 'Kochi',
            'alappuzha': 'Alleppey', 'bengaluru': 'Bangalore', 'mangaluru': 'Mangalore'}


def _clean(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()[:120]


def _queries(name: str) -> list[str]:
    """'North Goa (Calangute)' -> ['North Goa', 'Calangute', ...]; 'Along X to Y' -> ['Y']."""
    name = _clean(name)
    along = re.match(r'^along .+? to (.+)$', name, re.I)
    if along:
        name = along[1]
    first = name.split(',')[0]
    inner = re.findall(r'\(([^)]+)\)', first)
    outer = re.sub(r'\([^)]*\)', '', first).strip(' -–/')
    parts = [outer, *inner, *re.split(r'\s*[/&]\s*|\s+and\s+', outer)]
    queries = []
    for part in (_clean(p) for p in parts):
        queries += [_ALIASES[part.casefold()], part] if part.casefold() in _ALIASES else [part]
    return [q for q in dict.fromkeys(queries) if len(q) >= 2][:5]


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


async def _lookup(name: str, region: str, near: tuple[float, float] | None) -> dict | None:
    hints = {h.strip().casefold() for h in [*name.split(',')[1:], *region.split(',')] if h.strip()} - _IGNORED_HINTS
    for query in _queries(name):
        try:
            data = await fetch(GEOCODER, {'name': query, 'count': 10, 'language': 'en', 'countryCode': 'IN'})
        except Exception:
            continue
        candidates = [c for c in data.get('results', []) if c.get('country_code') == 'IN'
                      and c.get('latitude') is not None and c.get('longitude') is not None]
        hinted = [c for c in candidates if hints & {str(c.get(k, '')).casefold() for k in ('admin1', 'admin2', 'admin3')}]
        nearby = [c for c in candidates if near and _km(near, (c['latitude'], c['longitude'])) <= NEAR_KM]
        # A region or anchor rules out same-named places elsewhere in India.
        best = (hinted or nearby or ([] if hints or near else candidates))[:1]
        if best:
            c = best[0]
            return {'name': c['name'], 'admin1': c.get('admin1'), 'lat': float(c['latitude']), 'lon': float(c['longitude'])}
    return None


async def geocode_points(places: list[dict]) -> list[dict | None]:
    """Each place is {'name', 'region'?, 'near'?: [lat, lon]}."""
    if get_settings().app_mode != 'live':
        return [None] * len(places)

    async def one(place: dict):
        near = tuple(place['near']) if place.get('near') else None
        key = (place['name'].casefold().strip(), place.get('region', '').casefold().strip(), near)
        if key not in _cache:
            _cache[key] = await _lookup(place['name'], place.get('region', ''), near)
        return _cache[key]

    return list(await asyncio.gather(*(one(p) for p in places)))
