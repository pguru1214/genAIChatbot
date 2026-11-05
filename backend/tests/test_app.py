import json

import pytest
from fastapi.testclient import TestClient

from app.agents import graph, validate
from app.main import app
from app.tools import get_weather


def stream_result(response):
    assert response.status_code == 200
    frames = response.text.split('\n\n')
    return [json.loads(line[6:]) for frame in frames if frame.startswith('event: completed')
            for line in frame.splitlines() if line.startswith('data: ')][0]['result']


def request(**overrides):
    return {'message': 'Plan my trip', 'destination': 'Jaipur', 'origin': 'Delhi', 'days': 2, **overrides}


def test_health_and_validation():
    with TestClient(app) as client:
        assert client.get('/api/health').json()['mode'] == 'demo'
        for bad in [request(days=0), request(destination=' '), request(timezone='fake/zone'), request(message='')]:
            assert client.post('/api/chat', json=bad).status_code == 422


def test_plan_stream_persist_delete():
    with TestClient(app) as client:
        response = client.post('/api/chat', json=request())
        result = stream_result(response)
        assert result['agent_trace'] == ['India Tourism Router', 'Travel Research Agent', 'Connectivity Planner', 'Itinerary Agent']
        assert 'DEMO' in result['answer']
        assert response.text.index('event: progress') < response.text.index('event: completed')
        assert any(t['id'] == result['trip_id'] for t in client.get('/api/trips').json())
        assert client.delete('/api/trips/' + result['trip_id']).status_code == 200
        assert client.delete('/api/trips/' + result['trip_id']).status_code == 404


def test_research_bypasses_planner():
    with TestClient(app) as client:
        result = stream_result(client.post('/api/chat', json=request(message='What is the weather?')))
        assert result['agent_trace'] == ['India Tourism Router', 'Travel Research Agent']
        assert 'No live weather' in result['answer']


def test_action_preview_cannot_send():
    with TestClient(app) as client:
        saved = stream_result(client.post('/api/chat', json=request()))
        result = stream_result(client.post('/api/chat', json=request(intent='email', trip_id=saved['trip_id'])))
        assert result['agent_trace'] == ['Action Agent']
        assert result['action']['execution_enabled'] is False
        assert saved['answer'] in result['answer']
        assert client.post('/api/proposals/' + result['proposal_id'] + '/approve').status_code == 501
        assert client.post('/api/chat', json=request(intent='email')).status_code == 422
        assert client.post('/api/chat', json=request(intent='calendar', trip_id='missing')).status_code == 404


def test_unknown_sources_rejected():
    with pytest.raises(ValueError, match='unknown source'):
        validate({'source_ids': ['invented'], 'research': {'evidence': []}})


async def test_weather_outside_window_does_not_call_provider():
    result = await get_weather.ainvoke({'latitude': 26.9, 'longitude': 75.8, 'start_date': '2000-01-01', 'days': 2})
    assert result['available'] is False


async def test_live_research_partial_failure(monkeypatch):
    import app.tools as tools

    async def fake_fetch(url, params):
        if 'geocoding' in url:
            return {'results': [{'name': 'Testcity', 'country': 'India', 'latitude': 26, 'longitude': 75}]}
        if 'wikipedia' in url:
            if params.get('generator') == 'geosearch':
                return {'query': {'pages': {'1': {'title': 'Museum', 'categories': [{'title': 'Category:Museums'}]}}}}
            raise TimeoutError()
        return {'elements': [{'id': 123, 'type': 'node', 'tags': {'name': 'Museum', 'tourism': 'museum'}}]}

    monkeypatch.setattr(tools, 'fetch', fake_fetch)
    data = await tools.collect_evidence({'destination': 'Testcity', 'days': 2}, False)
    assert data['mode'] == 'live'
    assert len(data['errors']) == 1
    assert data['evidence'][0]['data']['places'][0]['name'] == 'Museum'


async def test_ambiguous_location_requires_clarification(monkeypatch):
    import app.tools as tools

    async def fake_fetch(url, params):
        return {'results': [{'name': 'Samecity', 'country': 'India', 'admin1': 'A'}, {'name': 'Samecity', 'country': 'India', 'admin1': 'B'}]}

    monkeypatch.setattr(tools, 'fetch', fake_fetch)
    with pytest.raises(ValueError, match='more than one'):
        await tools.resolve_destination.ainvoke({'destination': 'Samecity'})


async def test_goa_region_resolves_without_city_api(monkeypatch):
    import app.tools as tools

    async def fake_fetch(url, params):
        raise AssertionError('State requests must resolve locally')

    monkeypatch.setattr(tools, 'fetch', fake_fetch)
    result = await tools.resolve_destination.ainvoke({'destination': 'Goa, India'})
    assert result['scope'] == 'state'
    assert result['country_code'] == 'IN'
    assert 'latitude' not in result


async def test_goa_in_another_country_is_rejected(monkeypatch):
    import app.tools as tools

    async def fake_fetch(url, params):
        return {'results': [{'name': 'Goa', 'country': 'Philippines', 'latitude': 13.7, 'longitude': 123.5}]}

    monkeypatch.setattr(tools, 'fetch', fake_fetch)
    with pytest.raises(tools.DestinationNeedsClarification, match='India only'):
        await tools.resolve_destination.ainvoke({'destination': 'Goa, Philippines'})


async def test_invalid_sources_fail_before_streaming(monkeypatch):
    import app.agents as agents
    from app.config import Settings

    async def fake_collect(*args):
        return {'evidence': [{'id': 'real'}]}

    async def fake_generate(*args):
        return {'answer': 'An unsupported claim', 'source_ids': ['invented']}

    monkeypatch.setattr(agents, 'get_settings', lambda: Settings(app_mode='live'))
    monkeypatch.setattr(agents, 'collect_evidence', fake_collect)
    monkeypatch.setattr(agents, 'generate', fake_generate)
    with pytest.raises(ValueError, match='unknown source'):
        await graph.ainvoke({'request': request(intent='research')})


def test_quick_chat_reports_ambiguous_destination(monkeypatch):
    import app.agents as agents
    from app.tools import DestinationNeedsClarification

    async def ambiguous(*args):
        raise DestinationNeedsClarification('Which Jaipur? Use Jaipur, Rajasthan, India.')

    monkeypatch.setattr(agents, 'collect_evidence', ambiguous)
    with TestClient(app) as client:
        response = client.post('/api/chat', json=request())
        error = next(json.loads(line[6:]) for frame in response.text.split('\n\n')
                     if frame.startswith('event: error') for line in frame.splitlines() if line.startswith('data: '))
        assert error['code'] == 'destination_clarification'
        assert 'Jaipur, Rajasthan, India' in error['message']
        assert 'event: completed' not in response.text


async def test_all_research_providers_down_returns_honest_empty_evidence(monkeypatch):
    import app.tools as tools

    async def fake_fetch(url, params):
        if 'geocoding' in url:
            return {'results': [{'name': 'Testcity', 'country': 'India', 'latitude': 26, 'longitude': 75}]}
        raise TimeoutError('sensitive provider details')

    monkeypatch.setattr(tools, 'fetch', fake_fetch)
    result = await tools.collect_evidence({'destination': 'Testcity', 'days': 3}, False)
    assert result['evidence'] == []
    assert len(result['errors']) == 2
    assert 'sensitive' not in json.dumps(result)


def test_provider_error_details_are_not_exposed():
    from app.errors import public_error

    class QuotaError(Exception):
        code = 429

    error = public_error(QuotaError('api_key=secret-value'))
    assert error['code'] == 'provider_quota'
    assert 'secret-value' not in json.dumps(error)
    assert 'secret-value' not in json.dumps(public_error(RuntimeError('api_key=secret-value')))
