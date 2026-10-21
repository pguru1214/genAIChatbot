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
    return {'message': 'Plan my trip', 'destination': 'Jaipur', 'days': 2, **overrides}


def test_health_and_validation():
    with TestClient(app) as client:
        assert client.get('/api/health').json()['mode'] == 'demo'
        for bad in [request(days=0), request(destination=' '), request(timezone='fake/zone'), request(message='')]:
            assert client.post('/api/chat', json=bad).status_code == 422


def test_plan_stream_persist_delete():
    with TestClient(app) as client:
        response = client.post('/api/chat', json=request())
        result = stream_result(response)
        assert result['agent_trace'] == ['Travel Research Agent', 'Itinerary Agent']
        assert 'DEMO' in result['answer']
        assert response.text.index('event: progress') < response.text.index('event: completed')
        assert any(t['id'] == result['trip_id'] for t in client.get('/api/trips').json())
        assert client.delete('/api/trips/' + result['trip_id']).status_code == 200
        assert client.delete('/api/trips/' + result['trip_id']).status_code == 404


def test_research_bypasses_planner():
    with TestClient(app) as client:
        result = stream_result(client.post('/api/chat', json=request(message='What is the weather?')))
        assert result['agent_trace'] == ['Travel Research Agent']
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
        return {'results': [{'name': 'Samecity', 'country': 'A'}, {'name': 'Samecity', 'country': 'B'}]}

    monkeypatch.setattr(tools, 'fetch', fake_fetch)
    with pytest.raises(ValueError, match='Ambiguous'):
        await tools.resolve_destination.ainvoke({'destination': 'Samecity'})


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
