"""Bounded, free-tier-only Geoapify access shared by all place/routing lookups."""
import asyncio
import hashlib
import sqlite3
import time
from pathlib import Path

import httpx

from app.config import get_settings


USAGE_PATH = Path(__file__).resolve().parents[1] / '.cache' / 'geoapify-usage.sqlite3'
ALLOWED = {'https://api.geoapify.com/v1/geocode/search',
           'https://api.geoapify.com/v1/routing', 'https://api.geoapify.com/v2/places'}


class FreeQuotaExceeded(ValueError):
    pass


def reserve(key, limit):
    """Persist a conservative rolling-24-hour allowance, including failed calls.

    Two credits are reserved per bounded request (no extras/large result sets).
    This ledger is shared across processes and survives a backend restart.
    Other applications using the same provider account are outside this ledger.
    """
    USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(USAGE_PATH, timeout=5) as db:
        db.execute('CREATE TABLE IF NOT EXISTS usage (account TEXT, created REAL, cost INTEGER)')
        db.execute('BEGIN IMMEDIATE')
        now = time.time()
        account = hashlib.sha256(key.encode()).hexdigest()
        db.execute('DELETE FROM usage WHERE created < ?', (now - 86400,))
        total, last = db.execute('SELECT COALESCE(SUM(cost), 0), COALESCE(MAX(created), 0) '
                                'FROM usage WHERE account = ?', (account,)).fetchone()
        if total + 2 > min(limit, 3000):
            raise FreeQuotaExceeded('The local free API allowance is exhausted. Try again after it resets.')
        scheduled = max(now, last + .26)
        db.execute('INSERT INTO usage VALUES (?, ?, ?)', (account, scheduled, 2))
    return max(0, scheduled - now)


async def geoapify_fetch(url, params):
    if url not in ALLOWED:
        raise ValueError('Unsupported Geoapify endpoint')
    if url.endswith('/places') and int(params.get('limit', 20)) > 20:
        raise ValueError('Free-only place lookups are limited to 20 results')
    if url.endswith('/routing') and len(params.get('waypoints', '').split('|')) != 2:
        raise ValueError('Free-only routing is limited to one waypoint pair per request')
    # No premium request options or arbitrary model-generated URLs are accepted.
    if any(k in params for k in ('details', 'features', 'elevation', 'avoid', 'alternatives')):
        raise ValueError('Extra-cost provider options are disabled')
    settings = get_settings()
    delay = await asyncio.to_thread(reserve, params['apiKey'], settings.geoapify_daily_credit_limit)
    await asyncio.sleep(delay)
    async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
        response = await client.get(url, params=params)
        if response.status_code == 429:
            raise FreeQuotaExceeded('The provider free quota or rate limit was reached. Try again later.')
        response.raise_for_status()
        if len(response.content) > 2_000_000:
            raise ValueError('Provider response too large')
        return response.json()
