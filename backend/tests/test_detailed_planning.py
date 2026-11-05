from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.itinerary import schedule_schema, render_schedule, connectivity_context
from app.planning import planning_defaults


def preferences():
    return {'origin': 'Delhi', 'destination': 'Jaipur, Rajasthan, India', 'days': 3, 'timezone': 'Asia/Kolkata'}


def test_defaults_are_local_next_week_and_preserve_explicit_preferences():
    details, applied = planning_defaults(preferences())
    assert details['start_date'] == (datetime.now(ZoneInfo('Asia/Kolkata')).date() + timedelta(days=7)).isoformat()
    assert details['budget'] == '50000'
    assert (details['day_start'], details['day_end']) == ('10:00', '18:00')
    explicit = {**details, 'start_date': '2099-02-03', 'budget': '15000', 'day_start': '09:00', 'day_end': '17:00'}
    unchanged, new = planning_defaults(explicit)
    assert unchanged == explicit
    assert not new


def test_missing_origin_is_asked_while_defaults_are_kept():
    with TestClient(app) as client:
        cid = client.post('/api/conversations').json()['id']
        response = client.post(f'/api/conversations/{cid}/messages', json={'message': 'Apply trip details',
            'details': {'destination': 'Goa, India', 'days': 3}})
        assert 'event: error' not in response.text
        view = client.get(f'/api/conversations/{cid}').json()
        assert view['pending']['field'] == 'origin'
        assert view['details']['budget'] == '50000'
        assert view['details']['day_start'] == '10:00'
        date = view['details']['start_date']
        response = client.post(f'/api/conversations/{cid}/messages', json={'message': 'Mumbai', 'checkpoint_id': view['checkpoint_id']})
        assert 'event: error' not in response.text
        view = client.get(f'/api/conversations/{cid}').json()
        assert view['pending'] is None
        assert view['details']['origin'] == 'Mumbai'
        assert view['details']['start_date'] == date
        saved = client.get(f'/api/trips/{cid}').json()
        assert saved['details']['origin'] == 'Mumbai'
        assert len(saved['result']['schedule']) == 3


def test_schedule_computes_ordered_times_and_next_attraction(itinerary_payload):
    request, _ = planning_defaults(preferences())
    research = {'evidence': [{'id': 'source-1'}]}
    plan = schedule_schema(request, research).model_validate(itinerary_payload())
    result = render_schedule(plan, request, connectivity_context(request, research))
    slots = result['schedule'][0]['activities']
    assert (slots[0]['start'], slots[0]['end']) == ('10:00', '11:30')
    assert slots[0]['next_attraction'] == 'Second attraction'
    assert all(a['end'] <= b['start'] for a, b in zip(slots, slots[1:]))
    assert slots[-1]['end'] <= '18:00'
    assert '90 min (estimate)' in result['answer']
    assert 'unverified' in result['answer']


@pytest.mark.parametrize('violation', ['overbooked', 'missing-day', 'no-meal', 'no-transfer', 'unknown-source', 'over-budget'])
def test_bad_schedules_are_rejected(violation, itinerary_payload):
    request, _ = planning_defaults(preferences())
    payload = itinerary_payload()
    if violation == 'overbooked':
        payload['days'][0]['activities'][0]['duration_minutes'] = 480
    elif violation == 'missing-day':
        payload['days'].pop()
    elif violation == 'no-meal':
        for a in payload['days'][0]['activities']:
            if a['kind'] == 'meal':
                a['kind'] = 'break'
    elif violation == 'no-transfer':
        for a in payload['days'][0]['activities']:
            if a['kind'] == 'transfer':
                a['kind'] = 'break'
    elif violation == 'unknown-source':
        payload['source_ids'] = ['invented']
    else:
        payload['budget_allocation'][0]['amount'] = 50001
    with pytest.raises(ValidationError):
        schedule_schema(request, {'evidence': [{'id': 'source-1'}]}).model_validate(payload)


def test_quick_plan_requires_origin_before_travel_lookups(monkeypatch):
    import app.agents as agents

    async def forbidden(*args):
        raise AssertionError('Missing origin must be asked before provider research')

    monkeypatch.setattr(agents, 'collect_evidence', forbidden)
    with TestClient(app) as client:
        response = client.post('/api/chat', json={'message': 'Plan my trip', 'destination': 'Goa'})
        assert '"field": "origin"' in response.text
        assert 'event: completed' not in response.text


def test_invalid_window_is_rejected_and_islands_do_not_assume_a_road_connection():
    with TestClient(app) as client:
        response = client.post('/api/chat', json={**preferences(), 'message': 'Plan my trip', 'day_start': '18:00', 'day_end': '10:00'})
        assert response.status_code == 422
    context = connectivity_context({**preferences(), 'destination': 'Lakshadweep, India'}, {})
    assert context['modes_to_consider'] == ['flight', 'sea']


def test_provider_schema_is_simplified_but_local_validation_remains(itinerary_payload):
    from app.llm import provider_schema, checked_response
    from app.errors import ModelResponseError
    request, _ = planning_defaults(preferences())
    schema = schedule_schema(request, {'evidence': [{'id': 'source-1'}]})
    wire = provider_schema(schema.model_json_schema(), schema.allowed_source_ids)
    assert 'maxItems' not in wire['properties']['days']
    assert wire['$defs']['Activity']['properties']['kind']['enum']
    assert wire['$defs']['Activity']['properties']['source_ids']['items']['enum'] == ['source-1']
    bad = itinerary_payload()
    bad['days'][0]['activities'][0]['duration_minutes'] = 1000
    with pytest.raises(ModelResponseError) as failure:
        checked_response(bad, schema)
    assert 'exceed' in failure.value.feedback


def test_message_preferences_are_extracted_alongside_form_edits(monkeypatch):
    import app.conversations as conversations
    from app.config import Settings
    monkeypatch.setattr(conversations, 'get_settings', lambda: Settings(app_mode='live'))
    calls = []

    def extract(schema, messages, **kwargs):
        calls.append(messages)
        return schema(budget='25000', day_start='09:00', day_end='17:00')

    monkeypatch.setattr(conversations, 'invoke_structured', extract)
    state = conversations.collect({'details': preferences(), 'question': '', 'turn': {
        'message': 'Change my budget to 25000 and daily hours to 9am-5pm.',
        'details': {'interests': 'history'}, 'timezone': 'Asia/Kolkata'}})
    assert calls
    assert state['details']['budget'] == '25000'
    assert state['details']['day_start'] == '09:00'
    assert state['details']['interests'] == 'history'


def test_missing_transfer_can_only_use_spare_time_without_shortening_visits(itinerary_payload):
    from app.itinerary import repair_transfer_allowances
    request, _ = planning_defaults(preferences())
    payload = itinerary_payload()
    # Removing the two transfer slots leaves exactly enough spare time for
    # two 30-minute allowances. A longer visit must not be silently compressed.
    for day in payload['days']:
        day['activities'] = [a for a in day['activities'] if a['kind'] != 'transfer']
    plan = repair_transfer_allowances(payload, request, {'evidence': [{'id': 'source-1'}]})
    assert all(sum(a.duration_minutes for a in d.activities) == 480 for d in plan.days)
    assert all([a.duration_minutes for a in d.activities if a.kind == 'visit'] == [90, 120, 90] for d in plan.days)
    assert 'provisional' in plan.notes[-1]
    payload['days'][0]['activities'][0]['duration_minutes'] += 5
    for activity in payload['days'][0]['activities']:
        if activity['kind'] == 'break':
            activity['kind'] = 'meal'
    with pytest.raises(ValueError):
        repair_transfer_allowances(payload, request, {'evidence': [{'id': 'source-1'}]})


def test_five_day_overnight_trip_returns_honest_draft_without_impossible_clock_times(itinerary_payload):
    from app.itinerary import prepare_schedule
    request, _ = planning_defaults({**preferences(), 'destination': 'Kerala, India', 'days': 5})
    payload = itinerary_payload(5)
    for day in [payload['days'][0], payload['days'][-1]]:
        day['activities'] = [
            {'kind': 'transfer', 'title': 'Overnight intercity journey', 'duration_minutes': 840, 'description': 'Unverified estimate.'},
            {'kind': 'visit', 'title': 'Optional sightseeing', 'duration_minutes': 120, 'description': 'After arrival only.', 'source_ids': ['source-1']}]
    research = {'evidence': [{'id': 'source-1'}]}
    plan = prepare_schedule(payload, request, research)
    result = render_schedule(plan, request, connectivity_context(request, research))
    assert result['planning_status'] == 'needs_review'
    assert len(result['schedule']) == 5
    assert [leg.duration_minutes for leg in plan.travel_legs] == [840, 840]
    assert result['schedule'][0]['activities'] == []
    assert result['schedule'][0]['status'] == 'needs_review'
    assert result['schedule'][1]['status'] == 'scheduled'
    assert result['schedule'][1]['activities'][-1]['end'] <= '18:00'
    assert '14 hours' in result['answer']
    assert 'overnight' in result['answer']


def test_relaxed_day_is_not_rejected_for_leaving_free_time(itinerary_payload):
    from app.itinerary import prepare_schedule
    request, _ = planning_defaults({**preferences(), 'days': 1})
    payload = itinerary_payload(1)
    payload['days'][0]['activities'] = [
        {'kind': 'visit', 'title': 'Relaxed museum visit', 'duration_minutes': 90, 'description': 'Planning estimate.', 'source_ids': ['source-1']},
        {'kind': 'meal', 'title': 'Lunch', 'duration_minutes': 60, 'description': 'Meal suggestion.'}]
    research = {'evidence': [{'id': 'source-1'}]}
    plan = prepare_schedule(payload, request, research)
    result = render_schedule(plan, request, connectivity_context(request, research))
    assert result['planning_status'] == 'scheduled'
    assert 'Flexible buffer' in result['answer']


def test_overfull_day_does_not_erase_other_days_or_shorten_visits(itinerary_payload):
    from app.itinerary import prepare_schedule
    request, _ = planning_defaults(preferences())
    payload = itinerary_payload()
    payload['days'][0]['activities'] = [
        {'kind': 'visit', 'title': 'Long visit', 'duration_minutes': 400, 'description': 'Unchanged duration.', 'source_ids': ['source-1']},
        {'kind': 'meal', 'title': 'Lunch', 'duration_minutes': 120, 'description': 'Meal'}]
    research = {'evidence': [{'id': 'source-1'}]}
    plan = prepare_schedule(payload, request, research)
    result = render_schedule(plan, request, connectivity_context(request, research))
    assert result['schedule'][0]['status'] == 'needs_review'
    assert plan.days[0].activities[0].duration_minutes == 400
    assert result['schedule'][1]['status'] == 'scheduled'
    assert 'unscheduled' in result['answer']


def test_review_days_do_not_bypass_source_checks(itinerary_payload):
    from app.itinerary import prepare_schedule
    request, _ = planning_defaults(preferences())
    payload = itinerary_payload()
    payload['days'][0]['review_note'] = 'Needs timing review'
    payload['days'][0]['activities'][0]['source_ids'] = ['invented']
    with pytest.raises(ValidationError):
        prepare_schedule(payload, request, {'evidence': [{'id': 'source-1'}]})
