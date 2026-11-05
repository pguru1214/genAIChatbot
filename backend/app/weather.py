"""Attach provider weather to the final daily bases without relying on AI output."""
import asyncio
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.tools import fetch, get_weather


async def itinerary_weather(plan, request, research):
    today = datetime.now(ZoneInfo('Asia/Kolkata')).date()
    start = date.fromisoformat(request['start_date'])
    retrieved = datetime.now(timezone.utc).isoformat()
    semaphore = asyncio.Semaphore(3)

    async def lookup(base):
        async with semaphore:
            try:
                async with asyncio.timeout(18):
                    # A base must be a town, not a state centroid or a guessed location.
                    name = base.split(',')[0].strip()
                    data = await fetch('https://geocoding-api.open-meteo.com/v1/search',
                                       {'name': name, 'count': 20, 'countryCode': 'IN', 'language': 'en'})
                    candidates = [c for c in data.get('results', []) if c.get('country_code') == 'IN'
                                  and c.get('name', '').casefold() == name.casefold()]
                    state = research.get('tourism_route', {}).get('state') or research.get('location', {}).get('admin1')
                    if state:
                        candidates = [c for c in candidates if c.get('admin1', '').casefold() == state.casefold()]
                    if len(candidates) != 1:
                        return {'reason': 'A unique Indian base town could not be verified; no forecast guessed.'}
                    location = candidates[0]
                    forecast = await get_weather.ainvoke({'latitude': location['latitude'], 'longitude': location['longitude'],
                                                        'start_date': request['start_date'], 'days': request['days']})
                    return {'location': location['name'], 'daily': forecast.get('daily', {}), 'reason': forecast.get('reason')}
            except Exception:
                return {'reason': 'Weather provider could not be reached. Retry closer to departure.'}

    bases = list(dict.fromkeys(d.base for d in plan.days
                if today <= start + timedelta(days=d.day - 1) <= today + timedelta(days=15)))
    results = dict(zip(bases, await asyncio.gather(*(lookup(base) for base in bases))))
    output = {}
    for day in plan.days:
        when = (start + timedelta(days=day.day - 1)).isoformat()
        row = {'date': when, 'location': day.base, 'provider': 'Open-Meteo',
               'url': 'https://open-meteo.com/', 'retrieved_at': retrieved, 'available': False}
        if day.base not in results or not today <= date.fromisoformat(when) <= today + timedelta(days=15):
            row['reason'] = 'This date is outside the next 16 days; a live forecast is not available yet.'
        else:
            result = results[day.base]
            daily = result.get('daily', {})
            if when in daily.get('time', []):
                index = daily['time'].index(when)
                for key, provider_key in [('min_c', 'temperature_2m_min'), ('max_c', 'temperature_2m_max'),
                                          ('rain_probability', 'precipitation_probability_max')]:
                    values = daily.get(provider_key, [])
                    row[key] = values[index] if index < len(values) else None
                row['available'] = any(row.get(k) is not None for k in ('min_c', 'max_c', 'rain_probability'))
                row['location'] = result.get('location', day.base)
            if not row['available']:
                row['reason'] = result.get('reason') or 'The provider returned no forecast for this date.'
        output[day.day] = row
    return output


def weather_text(weather):
    if not weather['available']:
        return 'Weather unavailable: ' + weather['reason']
    temperature = (f"{weather['min_c']}–{weather['max_c']} °C" if weather.get('min_c') is not None
                   and weather.get('max_c') is not None else 'temperature unavailable')
    rain = f"{weather['rain_probability']}%" if weather.get('rain_probability') is not None else 'unavailable'
    return (f"Weather forecast for {weather['location']}: {temperature}; rain probability {rain}. "
            f"Source: Open-Meteo, retrieved {weather['retrieved_at']}. Forecasts can change.")
