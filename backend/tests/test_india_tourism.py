import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

import app.tourism as tourism
import app.tools as tools
from app.database import SessionLocal, TourismPage
from app.main import app


def test_directory_covers_states_and_uts_with_unique_sources():
    data = tourism.directory()
    assert len([r for r in data['regions'] if r['kind'] == 'state']) == 28
    assert len([r for r in data['regions'] if r['kind'] == 'ut']) == 8
    assert len({r['id'] for r in data['regions']}) == 36
    assert len(data['districts']) == 17
    assert all(s['url'].startswith('https://') for s in tourism.sources().values())
    with TestClient(app) as client:
        assert len(client.get('/api/tourism/directory').json()['regions']) == 36
        assert client.get('/api/health').json()['destination_scope'] == 'India'


@pytest.mark.parametrize('destination,scope,state', [
    ('Goa, India', 'state', 'Goa'), ('Pondicherry', 'ut', 'Puducherry'),
    ('North Goa district, Goa, India', 'district', 'Goa'),
    ('Jaipur district, Rajasthan, India', 'district', 'Rajasthan'),
    ('Coorg, Karnataka', 'city', 'Karnataka'),
    ('Kodagu, India', 'district', 'Karnataka'),
])
def test_local_routing(destination, scope, state):
    route = tourism.destination_route(destination)
    assert route['scope'] == scope
    assert route['state'] == state


def test_district_scope_survives_conversation_canonicalization():
    from app.conversations import resolve
    state = resolve({'details': {'destination': 'Jaipur district, Rajasthan, India'}})
    assert tourism.destination_route(state['details']['destination'])['scope'] == 'district'


async def test_live_country_filter_never_returns_foreign_choices(monkeypatch):
    async def fetch(url, params):
        assert params['countryCode'] == 'IN'
        return {'results': [
            {'name': 'Sameplace', 'country_code': 'JP', 'country': 'Japan'},
            {'name': 'Sameplace', 'country_code': 'IN', 'country': 'India', 'admin1': 'Kerala', 'latitude': 10, 'longitude': 76}]}

    monkeypatch.setattr(tools, 'fetch', fetch)
    result = await tools.resolve_destination.ainvoke({'destination': 'Sameplace'})
    assert result['country'] == 'India'
    with pytest.raises(tourism.DestinationNeedsClarification, match='India only'):
        await tools.resolve_destination.ainvoke({'destination': 'Sameplace, Japan'})


def test_demo_and_conversation_reject_foreign_destinations_without_losing_dates():
    with TestClient(app) as client:
        response = client.post('/api/chat', json={'message': 'Plan a trip', 'destination': 'Kyoto, Japan'})
        assert 'destination_clarification' in response.text
        assert 'event: completed' not in response.text
        cid = client.post('/api/conversations').json()['id']
        response = client.post(f'/api/conversations/{cid}/messages', json={'message': 'Apply trip details',
            'details': {'destination': 'Kyoto, Japan', 'start_date': '2099-11-11', 'days': 3}})
        assert 'event: error' not in response.text
        view = client.get(f'/api/conversations/{cid}').json()
        assert view['pending']['field'] == 'destination'
        assert 'India only' in view['pending']['question']
        assert view['details']['start_date'] == '2099-11-11'
        response = client.post(f'/api/conversations/{cid}/messages', json={'message': 'Goa, India',
            'checkpoint_id': view['checkpoint_id']})
        assert 'event: error' not in response.text
        assert client.get(f'/api/conversations/{cid}').json()['pending']['field'] == 'origin'


def test_state_selection_bounds_days_and_rejects_unknown_ids_and_cross_clusters():
    route = tourism.destination_route('Karnataka')
    chosen = tourism.select_districts(route, {'days': 7},
        ['https://evil.example', 'karnataka-mysuru', 'karnataka-vijayanagara', 'karnataka-kodagu'])
    assert [d['name'] for d in chosen] == ['Mysuru', 'Kodagu']
    assert len(tourism.select_districts(route, {'days': 3})) == 1
    assert tourism.select_districts(tourism.destination_route('Goa'), {'interests': 'relaxation', 'days': 3})[0]['name'] == 'South Goa'


async def test_source_id_allowlist_prevents_arbitrary_requests(monkeypatch):
    async def forbidden(*args):
        raise AssertionError('Unregistered addresses must never be requested')

    monkeypatch.setattr(tourism, 'download_page', forbidden)
    with pytest.raises(ValueError, match='Unknown tourism source'):
        await tourism.official_evidence('https://127.0.0.1/private')


async def test_persistent_cache_fresh_stale_and_expired(monkeypatch):
    sid = 'goa-south-goa'
    with SessionLocal() as session:
        if row := session.get(TourismPage, sid):
            session.delete(row)
            session.commit()
    calls = []

    async def download(url):
        calls.append(url)
        return 'Official tourism reference text. ' * 5

    monkeypatch.setattr(tourism, 'download_page', download)
    first = await tourism.official_evidence(sid)
    second = await tourism.official_evidence(sid)
    assert first['data']['cache_status'] == 'fetched'
    assert second['data']['cache_status'] == 'fresh-cache'
    assert len(calls) == 1

    async def unavailable(url):
        raise TimeoutError()

    monkeypatch.setattr(tourism, 'download_page', unavailable)
    def age_cache(days):
        with SessionLocal() as session:
            row = session.get(TourismPage, sid)
            row.payload = {**row.payload, 'retrieved_at': (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()}
            session.commit()
    age_cache(2)
    assert (await tourism.official_evidence(sid))['data']['cache_status'] == 'stale-cache'
    age_cache(8)
    with pytest.raises(TimeoutError):
        await tourism.official_evidence(sid)


def test_page_parser_excludes_scripts_and_navigation():
    parser = tourism.PageText()
    parser.feed('<nav>unrelated links</nav><script>secret code</script><main><h1>Goa tourism</h1><p>Colva Beach</p></main>')
    assert ' '.join(parser.parts) == 'Goa tourism Colva Beach'


async def test_regional_research_survives_official_outage_without_city_lookup(monkeypatch):
    async def forbidden(*args):
        raise AssertionError('A state must not use a city geocoder or nearby search')

    monkeypatch.setattr(tools, 'fetch', forbidden)
    result = await tools.collect_evidence({'destination': 'Goa, India', 'days': 4}, False)
    assert result['selected_districts'] == ['North Goa', 'South Goa']
    assert any(e['id'] == 'catalog-goa-north-goa' for e in result['evidence'])
    assert all(e['data'].get('reference_only') for e in result['evidence'])
    assert result['errors']


async def test_router_selects_before_retrieval_and_has_model_failure_fallback(monkeypatch):
    import app.agents as agents
    from app.config import Settings
    monkeypatch.setattr(agents, 'get_settings', lambda: Settings(app_mode='live'))

    async def unavailable(*args, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr(agents, 'ainvoke_structured', unavailable)
    result = await agents.tourism_router({'request': {'destination': 'Goa', 'days': 3, 'interests': 'relaxation'}})
    assert result['request']['_district_ids'] == ['goa-south-goa']
    assert result['agent_trace'] == ['India Tourism Router']


def test_state_live_graph_creates_and_saves_cited_ai_plan(monkeypatch, itinerary_payload):
    import app.agents as agents
    import app.conversations as conversations
    from app.config import Settings
    settings = Settings(app_mode='live')
    for module in [agents, conversations]:
        monkeypatch.setattr(module, 'get_settings', lambda: settings)

    async def generation(schema, messages, **kwargs):
        if schema is agents.TourismSelection:
            return schema(district_ids=['goa-north-goa', 'goa-south-goa', 'not-real'])
        assert 'Colva Beach' in messages[-1].content
        return schema.model_validate(itinerary_payload(4, ['catalog-goa-north-goa', 'catalog-goa-south-goa']))

    async def download(url):
        return 'Official Goa tourism information. ' * 10

    monkeypatch.setattr(tourism, 'download_page', download)
    monkeypatch.setattr(agents, 'ainvoke_structured', generation)
    with TestClient(app) as client:
        cid = client.post('/api/conversations').json()['id']
        response = client.post(f'/api/conversations/{cid}/messages', json={'message': 'Apply trip details', 'details': {
            'destination': 'Goa, India', 'origin': 'Mumbai', 'days': 4, 'start_date': '2099-11-11', 'budget': 'flexible',
            'currency': 'INR', 'interests': 'beaches', 'companions': 'solo'}})
        assert 'event: completed' in response.text, response.text
        assert 'event: error' not in response.text
        view = client.get(f'/api/conversations/{cid}').json()
        assert view['pending'] is None
        assert view['result']['trip_id'] == cid
        assert 'Packing checklist' in view['result']['answer']
        assert view['result']['research']['selected_districts'] == ['North Goa', 'South Goa']


def test_five_day_state_conversation_saves_partial_travel_review_without_error(monkeypatch, itinerary_payload):
    import app.agents as agents
    import app.conversations as conversations
    from app.config import Settings
    settings = Settings(app_mode='live')
    for module in [agents, conversations]:
        monkeypatch.setattr(module, 'get_settings', lambda: settings)
    async def generation(schema, messages, **kwargs):
        if schema is agents.TourismSelection:
            return schema(district_ids=['kerala-ernakulam', 'kerala-alappuzha'])
        payload = itinerary_payload(5, ['catalog-kerala-ernakulam'])
        payload['days'][0]['activities'] = [{'kind': 'transfer', 'title': 'Long intercity journey',
            'duration_minutes': 840, 'description': 'Transport timing must be checked.'}]
        return schema.model_validate(payload)
    monkeypatch.setattr(agents, 'ainvoke_structured', generation)
    with TestClient(app) as client:
        cid = client.post('/api/conversations').json()['id']
        response = client.post(f'/api/conversations/{cid}/messages', json={'message': 'Apply trip details', 'details': {
            'origin': 'Origin City', 'destination': 'Kerala, India', 'days': 5, 'start_date': '2099-11-12'}})
        assert 'event: completed' in response.text
        assert 'event: error' not in response.text
        view = client.get(f'/api/conversations/{cid}').json()
        assert view['result']['planning_status'] == 'needs_review'
        assert len(view['result']['schedule']) == 5
        assert view['result']['schedule'][1]['status'] == 'scheduled'
        assert view['result']['schedule'][0]['activities'] == []
        assert client.get(f'/api/trips/{cid}').json()['result']['planning_status'] == 'needs_review'
