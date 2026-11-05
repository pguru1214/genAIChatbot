import json
import pytest

from fastapi.testclient import TestClient

from app.main import app


def create(client):
    response = client.post('/api/conversations')
    assert response.status_code == 201
    return response.json()['id']


def turn(client, conversation_id, message, details=None):
    view = client.get(f'/api/conversations/{conversation_id}').json()
    response = client.post(f'/api/conversations/{conversation_id}/messages', json={
        'message': message, 'details': details or {}, 'checkpoint_id': view['checkpoint_id']})
    assert response.status_code == 200, response.text
    assert 'event: error' not in response.text, response.text
    frames = response.text.split('\n\n')
    return next(json.loads(line[6:])['conversation'] for frame in frames if frame.startswith('event: conversation')
                for line in frame.splitlines() if line.startswith('data: '))


def complete_details():
    return {'destination': 'Jaipur', 'start_date': '2099-12-10', 'days': 3, 'budget': '15000',
            'currency': 'INR', 'interests': 'history and local food', 'companions': 'solo'}


def test_graph_completes_plan():
    from langgraph.checkpoint.memory import InMemorySaver
    from app.conversations import build_conversation_graph
    from app.database import init_db
    init_db()
    graph = build_conversation_graph(InMemorySaver())
    result = graph.invoke({'turn': {'message': 'Plan my trip', 'details': complete_details(), 'timezone': 'Asia/Kolkata'}},
                          config={'configurable': {'thread_id': 'graph-test'}, 'recursion_limit': 12}, durability='sync')
    assert result['result']['trip_id'] == 'graph-test'


def test_clarification_survives_application_restart():
    with TestClient(app) as client:
        conversation_id = create(client)
        first = turn(client, conversation_id, 'Plan a Jaipur trip')
        assert first['details']['destination'] == 'Jaipur'
        assert first['pending']['field'] == 'start_date'
        assert len(first['messages']) == 2
    # Recreates graph and saver, using the same disk database, without in-memory state.
    with TestClient(app) as client:
        restored = client.get(f'/api/conversations/{conversation_id}').json()
        assert restored == first
        second = turn(client, conversation_id, '2099-12-10')
        assert second['details']['destination'] == 'Jaipur'
        assert second['details']['start_date'] == '2099-12-10'
        assert second['pending']['field'] == 'days'
        assert len(second['messages']) == 4


def test_full_plan_followup_and_no_duplicate_trip():
    with TestClient(app) as client:
        conversation_id = create(client)
        result = turn(client, conversation_id, 'Plan my trip', complete_details())
        assert result['pending'] is None
        assert result['result']['trip_id'] == conversation_id
        assert 'DEMO itinerary' in result['messages'][-1]['content']
        assert result['result']['agent_trace'] == ['India Tourism Router', 'Travel Research Agent', 'Itinerary Agent']
        changed = turn(client, conversation_id, 'Make it four days', {'days': 4})
        assert changed['details']['days'] == 4
        assert changed['details']['interests'] == 'history and local food'
        assert 'Day 4' in changed['result']['answer']
        assert len(changed['messages']) == 4
        trips = client.get('/api/trips').json()
        assert len([t for t in trips if t['id'] == conversation_id]) == 1


def test_each_detail_is_collected_and_threads_are_isolated():
    with TestClient(app) as client:
        one, two = create(client), create(client)
        view = turn(client, one, 'Hello')
        assert view['pending']['field'] == 'destination'
        for answer, expected in [('Jaipur', 'start_date'), ('2099-12-10', 'days'), ('3', 'budget'),
                                 ('15000', 'currency'), ('INR', 'interests'), ('History', 'companions')]:
            view = turn(client, one, answer)
            assert view['pending']['field'] == expected
        view = turn(client, one, 'solo')
        assert view['result']['trip_id'] == one
        assert client.get(f'/api/conversations/{two}').json()['messages'] == []


def test_past_date_and_stale_turn():
    with TestClient(app) as client:
        conversation_id = create(client)
        view = turn(client, conversation_id, 'Plan my trip', {**complete_details(), 'start_date': '2000-01-01'})
        assert view['pending']['field'] == 'start_date'
        assert 'past' in view['pending']['question']
        assert view['result'] is None
        assert client.post(f'/api/conversations/{conversation_id}/messages', json={'message': '2099-12-10'}).status_code == 409
        assert client.post('/api/conversations/missing/messages', json={'message': 'Hi'}).status_code == 404
        assert client.post(f'/api/conversations/{conversation_id}/messages', json={
            'message': 'Hi', 'details': {'days': 9}, 'checkpoint_id': view['checkpoint_id']}).status_code == 422


def test_failed_plan_resumes_without_duplicate_messages(monkeypatch):
    import app.conversations as conversations
    original = conversations.planning_graph

    class Failing:
        async def ainvoke(self, *args, **kwargs):
            raise RuntimeError('simulated secret provider response')

    with TestClient(app) as client:
        conversation_id = create(client)
        monkeypatch.setattr(conversations, 'planning_graph', Failing())
        response = client.post(f'/api/conversations/{conversation_id}/messages', json={
            'message': 'Plan my trip', 'details': complete_details()})
        assert 'event: error' in response.text
        assert 'simulated secret' not in response.text
        view = client.get(f'/api/conversations/{conversation_id}').json()
        assert view['recoverable']
        assert len(view['messages']) == 1
        monkeypatch.setattr(conversations, 'planning_graph', original)
        restored = turn(client, conversation_id, 'Retry saved turn')
        assert len(restored['messages']) == 2
        assert restored['result']['trip_id'] == conversation_id


def test_invalid_duration_can_be_corrected():
    with TestClient(app) as client:
        conversation_id = create(client)
        view = turn(client, conversation_id, 'Plan a Jaipur trip', {'start_date': '2099-12-10'})
        assert view['pending']['field'] == 'days'
        view = turn(client, conversation_id, '20 days')
        assert view['pending']['field'] == 'days'
        view = turn(client, conversation_id, '3 days')
        assert view['details']['days'] == 3
        assert view['pending']['field'] == 'budget'


def test_busy_and_invalid_timezone():
    with TestClient(app) as client:
        conversation_id = create(client)
        assert client.post(f'/api/conversations/{conversation_id}/messages', json={
            'message': 'Hello', 'timezone': 'Not/AZone'}).status_code == 422
        app.state.conversation_lock.acquire()
        try:
            assert client.post(f'/api/conversations/{conversation_id}/messages', json={'message': 'Hi'}).status_code == 409
        finally:
            app.state.conversation_lock.release()
        assert turn(client, conversation_id, 'Hi')['pending']['field'] == 'destination'


def test_failed_plan_accepts_corrected_details(monkeypatch):
    import app.conversations as conversations
    original = conversations.planning_graph

    class Failing:
        async def ainvoke(self, *args, **kwargs):
            raise ValueError('Ambiguous destination')

    with TestClient(app) as client:
        conversation_id = create(client)
        monkeypatch.setattr(conversations, 'planning_graph', Failing())
        client.post(f'/api/conversations/{conversation_id}/messages', json={
            'message': 'Plan my trip', 'details': complete_details()})
        monkeypatch.setattr(conversations, 'planning_graph', original)
        result = turn(client, conversation_id, 'Use Udaipur instead', {'destination': 'Udaipur'})
        assert result['details']['destination'] == 'Udaipur'
        assert 'Udaipur' in result['result']['answer']
        assert len(result['messages']) == 3


def test_location_ambiguity_pauses_and_resumes(monkeypatch):
    import app.conversations as conversations
    from app.tools import DestinationNeedsClarification
    original = conversations.planning_graph

    class Ambiguous:
        async def ainvoke(self, *args, **kwargs):
            raise DestinationNeedsClarification('Which Jaipur? Reply Jaipur, Rajasthan, India.')

    with TestClient(app) as client:
        conversation_id = create(client)
        monkeypatch.setattr(conversations, 'planning_graph', Ambiguous())
        view = turn(client, conversation_id, 'Plan my trip', complete_details())
        assert view['pending']['field'] == 'destination'
        assert 'Which Jaipur' in view['pending']['question']
        assert not view['recoverable']
        monkeypatch.setattr(conversations, 'planning_graph', original)
        view = turn(client, conversation_id, 'Jaipur, Rajasthan, India')
        assert view['details']['destination'] == 'Jaipur, Rajasthan, India'
        assert view['result']['trip_id'] == conversation_id


async def test_geocoder_respects_explicit_region_and_country(monkeypatch):
    import app.tools as tools

    async def fake_fetch(url, params):
        assert params['name'] == 'Jaipur, Rajasthan'
        assert params['countryCode'] == 'IN'
        return {'results': [
            {'name': 'Jaipur', 'country': 'India', 'admin1': 'Rajasthan', 'latitude': 26, 'longitude': 75},
            {'name': 'Jaipur', 'country': 'Bangladesh', 'admin1': 'Sylhet', 'latitude': 25, 'longitude': 92}]}

    monkeypatch.setattr(tools, 'fetch', fake_fetch)
    result = await tools.resolve_destination.ainvoke({'destination': 'Jaipur, Rajasthan, India'})
    assert result['country'] == 'India'
    import pytest
    with pytest.raises(tools.DestinationNeedsClarification, match='India only'):
        await tools.resolve_destination.ainvoke({'destination': 'Jaipur, Imaginary Region, India'})


def test_real_nested_graph_location_pause_is_not_reported_as_failure(monkeypatch):
    import app.agents as agents
    import app.main as main
    from app.tools import DestinationNeedsClarification
    errors = []
    original = main.public_error

    async def ambiguous(*args):
        raise DestinationNeedsClarification('Which Jaipur? Reply Jaipur, Rajasthan, India.')

    def capture(error):
        errors.append((type(error).__name__, str(error)))
        return original(error)

    monkeypatch.setattr(agents, 'collect_evidence', ambiguous)
    monkeypatch.setattr(main, 'public_error', capture)
    with TestClient(app) as client:
        cid = create(client)
        response = client.post(f'/api/conversations/{cid}/messages', json={
            'message': 'Plan my trip', 'details': complete_details()})
        assert not errors, errors
        assert 'event: error' not in response.text
        view = client.get(f'/api/conversations/{cid}').json()
        assert view['pending']['field'] == 'destination'


@pytest.mark.parametrize('question,message,field,value', [
    ('start_date', '2027-11-02', 'start_date', '2027-11-02'),
    ('days', '3 days', 'days', 3), ('currency', 'inr', 'currency', 'INR'),
    ('budget', '15000', 'budget', '15000'), ('companions', 'solo', 'companions', 'solo'),
    ('interests', 'history and local food', 'interests', 'history and local food'),
    ('destination', 'Jaipur, Rajasthan, India', 'destination', 'Jaipur, Rajasthan, India'),
])
def test_plain_replies_work_during_gemini_outage(monkeypatch, question, message, field, value):
    import app.conversations as conversations
    from app.config import Settings

    def unavailable(*args, **kwargs):
        raise AssertionError('A plain answer must not call Gemini')

    monkeypatch.setattr(conversations, 'get_settings', lambda: Settings(app_mode='live'))
    monkeypatch.setattr(conversations, 'invoke_structured', unavailable)
    state = conversations.collect({'question': question, 'details': {},
        'turn': {'message': message, 'details': {}, 'timezone': 'Asia/Calcutta'}})
    assert state['details'][field] == value
    assert state['details']['timezone'] == 'Asia/Calcutta'


def test_date_reply_and_location_choice_complete_live_graph_during_primary_outage(monkeypatch):
    import app.agents as agents
    import app.conversations as conversations
    import app.llm as llm
    import app.tools as tools
    from app.config import Settings

    settings = Settings(app_mode='live', gemini_model='primary', gemini_fallback_model='fallback')
    for module in [agents, conversations, llm]:
        monkeypatch.setattr(module, 'get_settings', lambda: settings)

    def no_extraction(*args, **kwargs):
        raise AssertionError('Date, choices and explicit form fields need no extraction call')

    monkeypatch.setattr(conversations, 'invoke_structured', no_extraction)

    async def fetch(url, params):
        if 'geocoding' in url:
            return {'results': [
                {'name': 'Jaipur', 'admin1': 'Rajasthan', 'country': 'India', 'latitude': 26.9, 'longitude': 75.8},
                {'name': 'Jaipur', 'admin1': 'Sylhet', 'country': 'Bangladesh', 'latitude': 25, 'longitude': 92}]}
        if 'wikipedia' in url:
            return {'query': {'pages': {'1': {'title': 'Jaipur', 'extract': 'A historic city.', 'fullurl': 'https://en.wikipedia.org/wiki/Jaipur'}}}}
        return {'elements': [{'id': 7, 'type': 'node', 'tags': {'name': 'Museum', 'tourism': 'museum'}}]}

    monkeypatch.setattr(tools, 'fetch', fetch)
    calls = []

    class Model:
        def __init__(self, name):
            self.name = name

        async def ainvoke(self, messages):
            calls.append(self.name)
            if self.name == 'primary':
                raise RuntimeError('503 UNAVAILABLE. high demand')
            return agents.AgentOutput(answer='Day 1: Museum.\nDay 2: Local food.\nDay 3: Relax.\nPacking checklist: shoes, charger.', source_ids=['source-1'])

    async def no_wait(_):
        pass

    monkeypatch.setattr(llm.asyncio, 'sleep', no_wait)
    monkeypatch.setattr(llm, 'structured_model', lambda name, *args: Model(name))
    with TestClient(app) as client:
        cid = create(client)
        view = turn(client, cid, '2027-11-02', {'destination': 'Jaipur', 'days': 3})
        assert view['details']['start_date'] == '2027-11-02'
        assert view['details']['destination'] == 'Jaipur, Rajasthan, India'
        assert view['pending']['field'] == 'budget'
        view = turn(client, cid, 'Apply trip details', {'budget': 'flexible', 'currency': 'INR',
            'interests': 'history', 'companions': 'solo'})
        assert view['pending'] is None
        assert 'Day 3' in view['result']['answer']
        assert 'Packing checklist' in view['result']['answer']
        assert calls == ['primary', 'primary', 'fallback']
        assert client.get(f'/api/conversations/{cid}').json()['result']['trip_id'] == cid
