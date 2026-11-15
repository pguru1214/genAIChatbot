import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app import transport as t


def request(mode='train', **changes):
    values = dict(mode=mode, origin='Mysuru', destination='Bengaluru',
                  date=(datetime.now(t.INDIA).date() + timedelta(days=7)).isoformat())
    return t.SearchRequest(**(values | changes))


@pytest.fixture
def connected(monkeypatch):
    monkeypatch.setattr(t, 'get_settings', lambda: SimpleNamespace(
        app_mode='live', railcore_api_key='test', travelpayouts_api_token='test'))
    t._reference_cache.clear()


@pytest.mark.parametrize('mode', ['bus', 'train', 'flight'])
def test_missing_credentials_never_call_provider(monkeypatch, mode):
    monkeypatch.setattr(t, 'get_settings', lambda: SimpleNamespace(
        app_mode='live', railcore_api_key='', travelpayouts_api_token=''))
    async def forbidden(*args):
        pytest.fail('No network call should occur')
    result = asyncio.run(t.search_transport(request(mode), forbidden))
    assert not result['offers']
    assert result['status'] == ('external_search' if mode == 'bus' else 'not_connected')
    assert result['date'] in result['links'][0]['url']


def test_invalid_date_and_url_code_rejected():
    assert t.canonical('New Delhi') == t.canonical('Delhi')
    assert t.canonical(None) == ''
    with pytest.raises(ValidationError):
        request(date='2020-01-01')
    with pytest.raises(ValidationError):
        request(origin_code='https://evil.test')


def test_train_overnight_and_missing_station():
    row = dict(train_number='12345', from_station_code='MYS', to_station_code='SBC',
               departure_time='23:00', arrival_time='02:00', duration_minutes=180,
               classes=['SL'], availability_summary=[])
    offer = t.train_offer(row, request())
    assert datetime.fromisoformat(offer['arrival']).date() == request().date + timedelta(days=1)
    assert t.train_offer(row | {'from_station_code': None}, request()) is None
    assert t.train_offer(row | {'arrival_time': '03:00'}, request())['arrival'] is None


def test_flight_filters_date_currency_and_unsafe_link(connected):
    req = request('flight', origin='Mumbai', destination='Delhi')
    row = dict(origin='BOM', destination='DEL', departure_at=f'{req.date}T09:00:00+05:30',
               airline='AI', flight_number='123', price=4000, duration_to=120,
               link='https://evil.test/book')
    async def get(provider, url, params):
        if provider == 'airports':
            name, code = ('Mumbai', 'BOM') if params['term'] == 'Mumbai' else ('Delhi', 'DEL')
            return [dict(name=name, code=code, country_code='IN')]
        return {'data': [row, row | {'currency': 'USD'}, row | {'departure_at': '2020-01-01T09:00:00+05:30'}]}
    result = asyncio.run(t.search_transport(req, get))
    assert len(result['offers']) == 1
    assert result['offers'][0]['data_kind'] == 'cached_fare'
    assert result['offers'][0]['booking_url'] == 'https://www.aviasales.com/'


def test_provider_quota_falls_back(connected):
    async def get(*args):
        raise t.ProviderIssue('quota_exhausted', 'Free quota exhausted')
    result = asyncio.run(t.search_transport(request(), get))
    assert result['status'] == 'quota_exhausted'
    assert result['offers'] == []
    assert result['links']


def test_local_quota_is_enforced_without_storing_key(monkeypatch, tmp_path):
    path = tmp_path / 'usage.sqlite3'
    monkeypatch.setattr(t, 'USAGE_PATH', path)
    for _ in range(8):
        t.reserve('railcore', 'private-test-key')
    with pytest.raises(t.ProviderIssue):
        t.reserve('railcore', 'private-test-key')
    assert b'private-test-key' not in path.read_bytes()


def test_ambiguous_station_not_guessed():
    points = [dict(code='AAA', exact=True, major=True, state='A'),
              dict(code='BBB', exact=True, major=True, state='B')]
    assert t.choose_station(points) is None


def test_station_null_city_does_not_discard_valid_route(connected):
    req = request(origin='Kurnool', destination='Mysuru district, Karnataka, India')
    async def get(provider, url, params):
        if url.endswith('/stations/search'):
            code, name, state = ('KRNT', 'Kurnool', 'Andhra Pradesh') if params['q'] == 'Kurnool' else ('MYS', 'Mysuru', 'Karnataka')
            return {'data': {'results': [
                dict(station_code=code, station_name=name, city=name, state=state, country='IN', aliases=[]),
                dict(station_code='NULL', station_name='Other', city=None, state=None, country='IN', aliases=None)]}}
        assert params['from'] == 'KRNT' and params['to'] == 'MYS'
        return {'data': {'journey_date': str(req.date), 'trains': [dict(
            train_number='12785', from_station_code='KRNT', to_station_code='MYS',
            departure_time='22:20', arrival_time='09:30', duration_minutes=670)]}}
    result = asyncio.run(t.search_transport(req, get))
    assert result['status'] == 'results'
    assert result['offers'][0]['service_number'] == '12785'


def test_missing_airport_explains_coverage_without_fare_request(connected):
    async def get(provider, url, params):
        assert provider == 'airports'
        if params['term'] == 'Kurnool':
            return [{'code': 'NQY', 'name': 'Newquay', 'country_code': 'GB'}]
        return [{'code': 'MYQ', 'name': 'Mysore', 'country_code': 'IN'}]
    result = asyncio.run(t.search_transport(request('flight', origin='Kurnool'), get))
    assert result['status'] == 'choose_points'
    assert 'no Indian match for Kurnool' in result['notice']
    assert not result['offers']


def test_seat_enquiry_rejects_other_date(connected, monkeypatch):
    req = t.SeatRequest(train_number='12345', origin_code='MYS', destination_code='SBC',
                        date=request().date, travel_class='SL')
    async def get(*args):
        return {'data': dict(train_number='12345', from_station_code='MYS', to_station_code='SBC',
                             journey_date='2020-01-01', classes=[{'class_code': 'SL', 'available_count': 20}])}
    monkeypatch.setattr(t, 'provider_get', get)
    result = asyncio.run(t.availability(req))
    assert result['status'] == 'provider_error'
    assert result['classes'] == []
