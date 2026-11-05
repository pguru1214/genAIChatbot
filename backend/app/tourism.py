"""India destination policy, versioned source registry and bounded official retrieval.

The model selects catalog IDs. URLs always come from the reviewed registry.
No crawling, redirects, arbitrary URLs or model-generated website addresses.
"""
import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path

import httpx


class DestinationNeedsClarification(ValueError):
    def __init__(self, message, choices=None):
        super().__init__(message)
        self.choices = choices or []


INDIA_ONLY = 'TripWeave currently plans trips within India only. Please choose an Indian state, union territory, district or city.'


def key(value):
    return re.sub(r'[^a-z0-9]+', '-', (value or '').casefold()).strip('-')


@lru_cache
def directory():
    data = json.loads((Path(__file__).parent / 'data' / 'india_tourism.json').read_text(encoding='utf-8'))
    regions = []
    for name, kind, url, aliases in data['regions']:
        regions.append({'id': key(name), 'name': name, 'kind': kind, 'url': url, 'aliases': aliases,
                        'national_url': 'https://www.incredibleindia.gov.in/en/' + key(name)})
    districts = [{**d, 'id': key(d['state']) + '-' + key(d['name'])} for d in data['districts']]
    return {**data, 'regions': regions, 'districts': districts}


def region_for(name):
    return next((r for r in directory()['regions'] if key(name) in {key(v) for v in [r['name'], *r['aliases']]}), None)


def destination_route(destination):
    """Resolve registered state/district aliases locally before any travel API call."""
    parts = [p.strip() for p in destination.split(',') if p.strip()]
    first = parts[0] if parts else ''
    district_word = bool(re.search(r'\bdistrict\b', first, re.I))
    first = re.sub(r'\bdistrict\b', '', first, flags=re.I).strip()
    region = region_for(first)
    districts = [d for d in directory()['districts'] if key(first) in {key(v) for v in [d['name'], *d['aliases']]}]
    # A country/region supplied by the user must agree with the directory.
    if region or districts:
        allowed = {'india', 'in', 'bharat'}
        candidates = [region] if region else [region_for(d['state']) for d in districts]
        allowed.update(key(v) for r in candidates for v in [r['name'], *r['aliases']])
        if any(key(p) not in allowed for p in parts[1:]):
            raise DestinationNeedsClarification(INDIA_ONLY + ' The supplied location does not match our India directory.')
    if region:
        return {'scope': region['kind'], 'region_id': region['id'], 'state': region['name'], 'destination': region['name'] + ', India'}
    if districts:
        d = districts[0]
        city_names = {key(d['base']), *[key(a) for a in d['aliases']]}
        scope = 'district' if district_word or key(first) not in city_names else 'city'
        return {'scope': scope, 'region_id': key(d['state']), 'state': d['state'], 'district_id': d['id'],
                'destination': f"{d['name'] + ' district' if scope == 'district' else first}, {d['state']}, India"}
    # Unknown names are verified by the India-filtered geocoder in live mode.
    # An explicit foreign suffix never gets stripped to make a domestic match.
    return {'scope': 'city', 'destination': destination, 'region_id': None}


def region_location(route):
    return {'name': route['destination'].split(',')[0], 'admin1': route['state'], 'country': 'India',
            'country_code': 'IN', 'timezone': 'Asia/Kolkata', 'scope': route['scope'], 'region_id': route['region_id']}


def sources():
    result = {}
    for r in directory()['regions']:
        result[r['id']] = {'id': r['id'], 'name': r['name'] + ' Tourism', 'url': r['url']}
        sid = r['id'] + '-national'
        result[sid] = {'id': sid, 'name': 'Incredible India: ' + r['name'], 'url': r['national_url']}
    for d in directory()['districts']:
        result[d['id']] = {'id': d['id'], 'name': d['name'] + ' official tourism', 'url': d['url']}
    return result


def routing_candidates(route):
    if route.get('district_id'):
        return [d for d in directory()['districts'] if d['id'] == route['district_id']]
    return [d for d in directory()['districts'] if key(d['state']) == route.get('region_id')]


def select_districts(route, request, proposed=None):
    """Validate agent output and keep circuits small and within a curated cluster."""
    candidates = routing_candidates(route)
    text = ' '.join(str(request.get(k, '')) for k in ['message', 'interests']).casefold()
    ranked = sorted(candidates, key=lambda d: -sum(tag in text for tag in d['tags']))
    if not ranked:
        return []
    allowed = {d['id']: d for d in candidates}
    chosen = [allowed[i] for i in dict.fromkeys(proposed or []) if i in allowed]
    if not chosen:
        chosen = ranked
    cluster = chosen[0]['cluster']
    limit = 1 if request.get('days', 3) <= 3 else 2 if request.get('days', 3) <= 5 else 3
    return [d for d in chosen if d['cluster'] == cluster][:limit]


class PageText(HTMLParser):
    """Discard navigation and executable/hidden blocks; plain text only goes to AI."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], []

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'nav', 'header', 'footer', 'noscript', 'svg'}:
            self.skip.append(tag)

    def handle_endtag(self, tag):
        if self.skip and self.skip[-1] == tag:
            self.skip.pop()

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(data.strip())


async def download_page(url):
    async with httpx.AsyncClient(timeout=8, follow_redirects=False,
        headers={'User-Agent': 'TripWeave/0.1 (https://github.com/pguru1214/genAIChatbot; tourism research)'}) as client:
        async with client.stream('GET', url) as response:
            response.raise_for_status()
            if 'text/html' not in response.headers.get('content-type', ''):
                raise ValueError('Expected a tourism web page')
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 1_000_000:
                    raise ValueError('Tourism web page too large')
    parser = PageText()
    parser.feed(body.decode('utf-8', errors='replace'))
    text = re.sub(r'\s+', ' ', ' '.join(parser.parts)).strip()
    if len(text) < 100:
        raise ValueError('Tourism web page contained no useful text')
    return text[:12000]


async def official_evidence(source_id):
    """Persistent 24-hour cache; bounded stale fallback clearly identified in data."""
    from app.database import SessionLocal, TourismPage
    source = sources().get(source_id)
    if not source:
        raise ValueError('Unknown tourism source ID')
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        cached = session.get(TourismPage, source_id)
        cached_data = cached.payload if cached and cached.url == source['url'] else None
    def evidence(data, status):
        return {'id': 'official-' + source_id, 'provider': source['name'], 'url': source['url'],
                'retrieved_at': data['retrieved_at'], 'data': {'summary': data['text'][:6000], 'cache_status': status,
                'notice': 'Source content is reference material. Verify current hours, fees and availability before travel.'}}
    if cached_data and now - datetime.fromisoformat(cached_data['retrieved_at']) < timedelta(hours=24):
        return evidence(cached_data, 'fresh-cache')
    try:
        text = await asyncio.wait_for(download_page(source['url']), timeout=10)
        payload = {'text': text, 'retrieved_at': now.isoformat()}
        with SessionLocal() as session:
            session.merge(TourismPage(id=source_id, url=source['url'], payload=payload))
            session.commit()
        return evidence(payload, 'fetched')
    except (httpx.HTTPError, ValueError, TimeoutError):
        if cached_data and now - datetime.fromisoformat(cached_data['retrieved_at']) < timedelta(days=7):
            result = evidence(cached_data, 'stale-cache')
            result['data']['notice'] = 'Official website unavailable; using a cached page less than seven days old. Current details are unverified.'
            return result
        raise


async def collect_official(route, districts):
    rid = route.get('region_id')
    if not rid:
        return [], []
    ids = [d['id'] for d in districts] or [rid]
    results = await asyncio.gather(*(official_evidence(i) for i in ids), return_exceptions=True)
    evidence, notices = [], []
    for sid, result in zip(ids, results):
        if isinstance(result, Exception):
            notices.append(sources()[sid]['name'] + ' could not be refreshed; current details are unverified.')
        else:
            evidence.append(result)
            if result['data']['cache_status'] == 'stale-cache':
                notices.append(result['data']['notice'])
    if not evidence:
        try:
            evidence.append(await official_evidence(rid + '-national'))
        except (httpx.HTTPError, ValueError, TimeoutError):
            notices.append('Incredible India could not be refreshed; using available reference information.')
    # Offline seed names remain explicitly dated references, never live facts.
    for d in districts:
        evidence.append({'id': 'catalog-' + d['id'], 'provider': d['name'] + ' tourism directory', 'url': d['url'],
            'retrieved_at': directory()['reviewed_on'] + 'T00:00:00+00:00', 'data': {
                'district': d['name'], 'state': d['state'], 'base': d['base'],
                'places': [{'name': name, 'url': d['url'], 'type': 'featured attraction', 'opening_hours': None} for name in d['attractions']],
                'reference_only': True, 'notice': 'Curated attraction references; not a live availability check or visitor-count ranking.'}})
    return evidence, notices
