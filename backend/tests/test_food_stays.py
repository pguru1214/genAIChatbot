import copy
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import food_stays as services, geoapify
from app.config import Settings
from app.food_stays import ServicePreferences, StopChoice
from app.itinerary import DetailedItinerary, render_schedule
from app.planning import planning_defaults


def request():
    return planning_defaults({'origin': 'Bengaluru, Karnataka, India', 'destination': 'Mysuru, Karnataka, India',
                              'days': 2, 'start_date': '2026-11-22'})[0]


def scheduled(itinerary_payload, days=2):
    payload = itinerary_payload(days)
    for day in payload['days']:
        day['base'] = 'Mysuru, Karnataka, India'
    result = render_schedule(DetailedItinerary.model_validate(payload), {**request(), 'days': days}, {})
    result['research'] = {'location': {'admin1': 'Karnataka'}}
    return result


def feature(name, point, category):
    return {'geometry': {'type': 'Point', 'coordinates': point}, 'properties': {
        'name': name, 'place_id': name, 'country_code': 'in', 'city': name, 'state': 'Karnataka', 'country': 'India',
        'formatted': name + ', Karnataka', 'categories': [category],
        'datasource': {'raw': {'cuisine': 'indian', 'wheelchair': 'yes', 'opening_hours': '08:00-22:00'}}}}


async def fake_provider(url, params):
    if url == services.GEOCODE:
        town = params['text'].split(',')[0]
        point = [72., 12.] if town == 'Bengaluru' else [80., 12.]
        return {'features': [feature(town, point, 'populated_place')]}
    if url == services.ROUTING:
        start, end = [list(map(float, pair.split(',')))[::-1] for pair in params['waypoints'].split('|')]
        seconds = max(60, abs(end[0] - start[0]) * 5400)
        points = [[start[0] + (end[0] - start[0]) * n / 100, start[1] + (end[1] - start[1]) * n / 100] for n in range(101)]
        return {'features': [{'geometry': {'type': 'MultiLineString', 'coordinates': [points]},
            'properties': {'time': seconds, 'distance': seconds * 12, 'legs': [{'steps': [
                {'time': seconds, 'from_index': 0, 'to_index': 100}]}]}}]}
    assert url == services.PLACES
    lon, lat, radius = params['filter'].split(':')[1].split(',')
    point = [float(lon), float(lat)]
    stay = params['categories'].startswith('accommodation')
    return {'features': [feature('Route Hotel' if stay else 'Indian Cafe', point,
                                 'accommodation.hotel' if stay else 'catering.restaurant')]}


def live(monkeypatch):
    monkeypatch.setattr(services, 'get_settings', lambda: Settings(app_mode='live', geoapify_api_key='test'))


def test_meal_windows_keep_visits_intact_and_never_overlap(itinerary_payload):
    result = scheduled(itinerary_payload)
    before = [a['duration_minutes'] for a in result['schedule'][0]['activities'] if a['kind'] == 'visit']
    services.reserve_meals(result, request())
    for day in result['schedule']:
        assert [(m['start'], m['end']) for m in day['meal_windows']] == [('08:00', '09:00'), ('13:00', '14:00'), ('20:00', '21:00')]
        candidates = day.get('unscheduled_options', day['activities'])
        assert [a['duration_minutes'] for a in candidates if a['kind'] == 'visit'] == before
        for activity in day['activities']:
            assert activity['end'] <= '12:45' or activity['start'] >= '14:15'
            assert activity['end'] <= request()['day_end']


@pytest.mark.asyncio
async def test_demo_and_missing_key_cover_every_day_without_network(monkeypatch, itinerary_payload):
    async def forbidden(*args):
        raise AssertionError('No API calls without live mode and a key')
    for mode in ('demo', 'live'):
        monkeypatch.setattr(services, 'get_settings', lambda: Settings(app_mode=mode, geoapify_api_key=''))
        output = await services.build_services(scheduled(itinerary_payload), request(), fetch=forbidden)
        assert len(output['days']) == 2
        assert all(len(d['meals']) == 3 for d in output['days'])
        assert output['notice']
        assert all(not d['destination_stays'] and d['stay_notice'] for d in output['days'])


@pytest.mark.asyncio
async def test_late_road_travel_has_verified_route_stays_and_review(monkeypatch, itinerary_payload):
    live(monkeypatch)
    result = scheduled(itinerary_payload)
    services.reserve_meals(result, request())
    prefs = ServicePreferences(transport_mode='car/taxi', departure_time='10:00')
    output = await services.build_services(result, request(), prefs, fetch=fake_provider)
    day = output['days'][0]
    assert day['overnight']['status'] == 'suggested'
    assert day['overnight']['places']
    assert all(p['arrival'][11:16] <= '22:00' for p in day['overnight']['places'])
    assert day['destination_stays'][0]['name'] == 'Route Hotel'
    assert len(day['meals']) == 3
    original = copy.deepcopy(output)
    choice = StopChoice(day=1, place_id=day['overnight']['places'][0]['id'])
    review = services.stop_review(output, choice)
    assert review['onward_departure'].startswith('2026-11-23T09:30')
    assert review['status'] == 'needs_review'
    assert output == original  # No automatic date/schedule mutation.
    with pytest.raises(ValueError):
        services.stop_review(output, StopChoice(day=1, place_id='invented'))


@pytest.mark.asyncio
async def test_transit_does_not_offer_arbitrary_roadside_hotel(monkeypatch, itinerary_payload):
    live(monkeypatch)
    calls = []
    async def fetch(url, params):
        calls.append(url)
        return await fake_provider(url, params)
    output = await services.build_services(scheduled(itinerary_payload), request(),
        ServicePreferences(transport_mode='train', departure_time='10:00'), fetch=fetch)
    assert services.ROUTING not in calls
    assert output['days'][0]['overnight']['status'] == 'timing_unknown'
    assert all(m['status'] == 'needs_review' for m in output['days'][0]['meals'])


@pytest.mark.asyncio
async def test_quota_failure_preserves_meals_and_does_not_retry(monkeypatch, itinerary_payload):
    live(monkeypatch)
    calls = []
    async def exhausted(*args):
        calls.append(args)
        raise geoapify.FreeQuotaExceeded('Free allowance exhausted')
    output = await services.build_services(scheduled(itinerary_payload), request(), fetch=exhausted)
    assert len(calls) == 1
    assert all(len(d['meals']) == 3 for d in output['days'])
    assert 'exhausted' in output['days'][1]['stay_notice']


def test_quota_persists_and_never_exceeds_configured_allowance(tmp_path, monkeypatch):
    monkeypatch.setattr(geoapify, 'USAGE_PATH', tmp_path / 'usage.sqlite3')
    geoapify.reserve('secret', 4)
    geoapify.reserve('secret', 4)
    with pytest.raises(geoapify.FreeQuotaExceeded):
        geoapify.reserve('secret', 4)
    assert b'secret' not in (tmp_path / 'usage.sqlite3').read_bytes()


@pytest.mark.asyncio
async def test_return_route_and_late_return_stays(monkeypatch, itinerary_payload):
    live(monkeypatch)
    output = await services.build_services(scheduled(itinerary_payload), request(),
        ServicePreferences(transport_mode='car/taxi', departure_time='08:00', return_departure_time='12:00'), fetch=fake_provider)
    home = output['days'][-1]['return_journey']
    assert home['journey']['destination'] == request()['origin']
    assert home['overnight']['status'] == 'suggested'
    assert home['overnight']['places']
    review = services.stop_review(output, StopChoice(day=2, place_id='Route Hotel', leg='return'))
    assert review['extends_trip']


def test_preferences_validate_times_and_provider_url_safety():
    with pytest.raises(ValueError):
        ServicePreferences(departure_time='25:00')
    assert services.safe_url('javascript:alert(1)') is None
    assert services.safe_url('https://example.com') == 'https://example.com'
    assert services.simple_hours_overlap('10:00-18:00', ('08:00', '09:00')) is False
    assert services.simple_hours_overlap('Mo-Su 10:00-18:00', ('13:00', '14:00')) is True
    assert services.simple_hours_overlap('22:00-02:00', ('20:00', '21:00')) is False
    assert services.simple_hours_overlap('Mo-Fr 08:00-18:00; PH off', ('08:00', '09:00')) is None
    assert services.simple_hours_overlap('24/7', ('20:00', '21:00')) is True


@pytest.mark.asyncio
@pytest.mark.parametrize('arrival, expected', [(1320, 'not_required'), (1321, 'suggested')])
async def test_overnight_threshold_is_strictly_after_22(monkeypatch, itinerary_payload, arrival, expected):
    live(monkeypatch)
    monkeypatch.setattr(services, 'road_clock', lambda *args: (arrival, []))
    output = await services.build_services(scheduled(itinerary_payload), request(),
        ServicePreferences(transport_mode='car/taxi', departure_time='10:00'), fetch=fake_provider)
    assert output['days'][0]['overnight']['status'] == expected


@pytest.mark.asyncio
async def test_ambiguous_geocoding_never_guesses_a_town(monkeypatch, itinerary_payload):
    live(monkeypatch)
    async def ambiguous(url, params):
        assert url == services.GEOCODE
        name = params['text'].split(',')[0]
        return {'features': [feature(name, [76, 12], 'populated_place'), feature(name, [78, 12], 'populated_place')]}
    output = await services.build_services(scheduled(itinerary_payload), request(), fetch=ambiguous)
    assert not output['days'][0]['destination_stays']
    assert 'could not be verified' in output['days'][0]['stay_notice']


@pytest.mark.asyncio
async def test_reported_preferences_and_unverified_venue_fields(monkeypatch):
    captured = []
    async def fetch(url, params):
        captured.append(params)
        return await fake_provider(url, params)
    lookup = services.Lookup('test', fetch)
    places = await lookup.places([76, 12], 'meal', ServicePreferences(dietary='vegan', accessibility=True, cuisine='indian'))
    assert captured[0]['conditions'] == 'wheelchair,vegan'
    assert places[0]['opening_hours'] == '08:00-22:00'
    assert 'rating' not in places[0] and 'price' not in places[0]
    assert not await lookup.places([76, 12], 'meal', ServicePreferences(cuisine='italian'))


def test_api_plan_has_food_stays_and_refresh_is_a_preview():
    from app.main import app
    with TestClient(app) as client:
        response = client.post('/api/chat', json={**request(), 'message': 'Plan my trip'})
        assert 'event: completed' in response.text
        import json
        completed = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ') and '"result"' in line][-1]
        result = completed['result']
        assert len(result['food_stays']['days']) == 2
        trip_id = result['trip_id']
        before = client.get(f'/api/trips/{trip_id}').json()
        preview = client.post(f'/api/trips/{trip_id}/food-stays', json={'dietary': 'vegan'})
        assert preview.status_code == 200
        assert preview.json()['food_stays']['preferences']['dietary'] == 'vegan'
        assert client.get(f'/api/trips/{trip_id}').json() == before
        bad = client.post(f'/api/trips/{trip_id}/overnight-review', json={
            'choice': {'day': 1, 'place_id': 'invented'}, 'preferences': {}})
        assert bad.status_code == 422
