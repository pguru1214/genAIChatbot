from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app import weather, tools
from app.itinerary import render_schedule, demo_schedule
from app.planning import planning_defaults


@pytest.mark.asyncio
async def test_regional_bases_get_daily_weather_and_partial_dates(monkeypatch):
    today = datetime.now(ZoneInfo('Asia/Kolkata')).date()
    start = today + timedelta(days=14)
    calls = []

    async def fetch(url, params):
        calls.append((url, params))
        if 'geocoding' in url:
            return {'results': [{'name': params['name'], 'country_code': 'IN', 'admin1': 'Kerala',
                                 'latitude': 9.9, 'longitude': 76.2}]}
        assert params['end_date'] == str(today + timedelta(days=15))
        return {'daily': {'time': [str(start), str(start + timedelta(days=1))],
                         'temperature_2m_min': [23, 24], 'temperature_2m_max': [30, 31],
                         'precipitation_probability_max': [70, 0]}}

    monkeypatch.setattr(weather, 'fetch', fetch)
    monkeypatch.setattr(tools, 'fetch', fetch)
    plan = SimpleNamespace(days=[SimpleNamespace(day=i, base=base) for i, base in
                                [(1, 'Kochi'), (2, 'Alappuzha'), (3, 'Alappuzha')]])
    result = await weather.itinerary_weather(plan, {'start_date': str(start), 'days': 3},
                                           {'tourism_route': {'state': 'Kerala'}})
    assert result[1]['available'] and result[1]['rain_probability'] == 70
    assert result[2]['available'] and result[2]['rain_probability'] == 0
    assert not result[3]['available'] and '16 days' in result[3]['reason']
    assert len(calls) == 4


@pytest.mark.asyncio
async def test_weather_failure_keeps_days_and_never_guesses_location(monkeypatch):
    async def unavailable(*args):
        raise TimeoutError()
    monkeypatch.setattr(weather, 'fetch', unavailable)
    plan = SimpleNamespace(days=[SimpleNamespace(day=1, base='Kochi')])
    result = await weather.itinerary_weather(plan, {'start_date': str(datetime.now(ZoneInfo('Asia/Kolkata')).date()), 'days': 1}, {})
    assert not result[1]['available']
    assert 'could not be reached' in result[1]['reason']


def test_forecast_is_rendered_and_persisted_with_daily_schedule():
    request, _ = planning_defaults({'origin': 'Delhi', 'destination': 'Kochi', 'days': 1})
    forecast = {1: {'available': True, 'location': 'Kochi', 'min_c': 23, 'max_c': 30,
                    'rain_probability': 0, 'retrieved_at': '2026-11-05T10:00:00+00:00'}}
    result = render_schedule(demo_schedule(request), request, {}, forecast)
    assert '23–30 °C; rain probability 0%' in result['answer']
    assert result['schedule'][0]['weather'] == forecast[1]
