"""Tool contracts and real stdio protocol checks; never use live API credentials."""
import asyncio
from datetime import timedelta
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import pytest
from starlette.testclient import TestClient

from app.mcp_servers import accommodation, attractions, travel
from app.mcp_servers.common import execute
from app.tourism import DestinationNeedsClarification


def payload(result):
    content, structured = result
    return structured


@pytest.mark.parametrize('module,names', [
    (travel, {'resolve_destination', 'get_destination_summary', 'get_weather', 'search_transport'}),
    (accommodation, {'search_stays', 'search_restaurants'}),
    (attractions, {'search_attractions', 'get_tourism_directory', 'get_official_tourism'}),
])
async def test_tool_discovery(module, names):
    tools = await module.create_server().list_tools()
    assert {tool.name for tool in tools} == names
    for tool in tools:
        assert tool.annotations.readOnlyHint
        assert tool.outputSchema['properties']['status']
        assert tool.description


async def test_attractions_preserve_source_and_fallback_notices(monkeypatch):
    provider = AsyncMock(return_value={'provider': 'Wikipedia nearby places', 'places': [{'name': 'Museum'}],
        'notices': ['Geoapify unavailable; Wikipedia fallback.'], 'attribution': 'Wikipedia contributors'})
    monkeypatch.setattr(attractions.tools, 'get_visitor_places', SimpleNamespace(ainvoke=provider))
    data = payload(await attractions.create_server().call_tool('search_attractions', {'latitude': 12, 'longitude': 77}))
    assert data['data']['places'][0]['name'] == 'Museum'
    assert data['data']['notices']
    assert data['data']['attribution'] == 'Wikipedia contributors'


@pytest.mark.parametrize('arguments', [
    {'latitude': 91, 'longitude': 0}, {'latitude': 0, 'longitude': -181},
    {'latitude': float('nan'), 'longitude': 0},
])
async def test_invalid_coordinates_rejected_before_provider(monkeypatch, arguments):
    provider = AsyncMock()
    monkeypatch.setattr(attractions.tools, 'get_visitor_places', SimpleNamespace(ainvoke=provider))
    with pytest.raises(Exception):
        await attractions.create_server().call_tool('search_attractions', arguments)
    provider.assert_not_awaited()


async def test_clarification_is_structured(monkeypatch):
    provider = AsyncMock(side_effect=DestinationNeedsClarification('Choose a city.', ['City A', 'City B']))
    monkeypatch.setattr(travel.tools, 'resolve_destination', SimpleNamespace(ainvoke=provider))
    data = payload(await travel.create_server().call_tool('resolve_destination', {'destination': 'Ambiguous'}))
    assert data['status'] == 'needs_clarification'
    assert data['data']['choices'] == ['City A', 'City B']


@pytest.mark.parametrize('error', [
    httpx.ConnectError('https://example.com/?apiKey=secret-key'),
    RuntimeError('postgresql://user:secret-key@host/db'),
])
async def test_errors_do_not_leak_credentials(error):
    async def fail():
        raise error
    result = await execute(fail)
    assert result.status == 'unavailable'
    assert 'secret-key' not in result.model_dump_json()


async def test_timeout_and_cancellation():
    result = await execute(lambda: asyncio.sleep(1), timeout=0.001)
    assert result.status == 'unavailable'
    async def cancel():
        raise asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await execute(cancel)


async def test_stays_without_key_returns_unavailable(monkeypatch):
    monkeypatch.setattr(accommodation, 'get_settings', lambda: SimpleNamespace(geoapify_api_key=''))
    data = payload(await accommodation.create_server().call_tool('search_stays', {'destination': 'Mysuru'}))
    assert data['status'] == 'unavailable'
    assert data['data'] == {}


@pytest.mark.parametrize('tool,arguments,kind', [
    ('search_stays', {'stay_preference': 'hotel', 'accessibility': True}, 'stay'),
    ('search_restaurants', {'dietary': 'vegan', 'cuisine': 'indian'}, 'meal'),
])
async def test_venue_search_passes_preferences_and_preserves_evidence(monkeypatch, tool, arguments, kind):
    lookup = SimpleNamespace(town=AsyncMock(return_value=[77, 12]), places=AsyncMock(return_value=[
        {'name': 'Sourced venue', 'url': 'https://www.openstreetmap.org/', 'retrieved_at': '2026-01-01'}]))
    monkeypatch.setattr(accommodation, 'get_settings', lambda: SimpleNamespace(geoapify_api_key='test'))
    monkeypatch.setattr(accommodation, 'Lookup', lambda key: lookup)
    data = payload(await accommodation.create_server().call_tool(tool, {'destination': 'Mysuru', 'radius_m': 1500, **arguments}))
    assert data['status'] == 'ok'
    call = lookup.places.call_args
    assert call.args[1] == kind
    assert call.kwargs['radius'] == 1500
    for key, value in arguments.items():
        assert getattr(call.args[2], key) == value
    assert data['data']['places'][0]['url']
    assert data['data']['attribution_url']
    assert 'not verified' in data['data']['notice']


async def test_official_tourism_keeps_reference_and_cache_status(monkeypatch):
    monkeypatch.setattr(attractions.tools, 'resolve_destination', SimpleNamespace(ainvoke=AsyncMock(
        return_value={'name': 'Kerala', 'country_code': 'IN'})))
    monkeypatch.setattr(attractions.tourism, 'collect_official', AsyncMock(return_value=([
        {'id': 'official-kerala', 'data': {'cache_status': 'stale-cache'}, 'retrieved_at': '2026-01-01'},
        {'id': 'catalog-example', 'data': {'reference_only': True}}], ['Cached page; current details unverified.'])))
    data = payload(await attractions.create_server().call_tool('get_official_tourism', {'destination': 'Kerala'}))
    assert data['data']['evidence'][0]['data']['cache_status'] == 'stale-cache'
    assert data['data']['evidence'][1]['data']['reference_only']
    assert data['data']['notices']


async def test_transport_uses_existing_status_and_date_validation(monkeypatch):
    provider = AsyncMock(return_value={'status': 'not_connected', 'offers': [], 'notice': 'Train provider not configured.'})
    monkeypatch.setattr(travel.transport, 'search_transport', provider)
    from app.transport import INDIA
    from datetime import datetime
    today = datetime.now(INDIA).date()
    server = travel.create_server()
    args = {'mode': 'train', 'origin': 'Delhi', 'destination': 'Jaipur', 'journey_date': today.isoformat()}
    data = payload(await server.call_tool('search_transport', args))
    assert data['data']['status'] == 'not_connected'
    assert data['data']['offers'] == []
    with pytest.raises(Exception):
        await server.call_tool('search_transport', {**args, 'journey_date': (today - timedelta(days=1)).isoformat()})
    assert provider.await_count == 1


@pytest.mark.parametrize('group,tool,args', [
    ('travel', 'get_weather', {'latitude': 12, 'longitude': 77, 'start_date': '2000-01-01', 'days': 1}),
    ('accommodation', 'search_stays', {'destination': 'Mysuru'}),
    ('attractions', 'get_tourism_directory', {'region': 'Kerala'}),
])
async def test_real_stdio_initialize_discover_and_call(group, tool, args, tmp_path):
    script = Path(__file__).resolve().parents[1] / 'run_mcp.py'
    env = {**os.environ, 'GEOAPIFY_API_KEY': '', 'APP_MODE': 'demo',
           'DATABASE_URL': 'sqlite:///' + str(tmp_path / 'mcp.db')}
    params = StdioServerParameters(command=sys.executable, args=[str(script), group], env=env, cwd=str(tmp_path))
    async with asyncio.timeout(30):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                assert tool in {t.name for t in listed.tools}
                result = await session.call_tool(tool, args)
                assert not result.isError
                assert result.structuredContent['status'] == ('ok' if group == 'attractions' else 'unavailable')
                if group == 'attractions':
                    assert result.structuredContent['data']['regions'][0]['name'] == 'Kerala'
                # Protocol-level validation must reject bad arguments too.
                invalid = await session.call_tool(tool, {'unexpected': 'invalid'}) if group != 'attractions' else await session.call_tool('search_attractions', {'latitude': 999, 'longitude': 0})
                assert invalid.isError


@pytest.mark.parametrize('module,tool,args', [
    (travel, 'get_weather', {'latitude': 12, 'longitude': 77, 'start_date': '2000-01-01'}),
    (accommodation, 'search_stays', {'destination': 'Mysuru'}),
    (attractions, 'get_tourism_directory', {'region': 'Kerala'}),
])
def test_streamable_http_protocol(module, tool, args, monkeypatch):
    monkeypatch.setattr(accommodation, 'get_settings', lambda: SimpleNamespace(geoapify_api_key=''))
    server = module.create_server(host='127.0.0.1', stateless_http=True, json_response=True)
    with TestClient(server.streamable_http_app(), base_url='http://127.0.0.1:8000') as client:
        headers = {'Accept': 'application/json, text/event-stream'}
        initialized = client.post('/mcp', headers=headers, json={
            'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                'protocolVersion': '2025-06-18', 'capabilities': {},
                'clientInfo': {'name': 'tripweave-test', 'version': '1.0'}}})
        assert initialized.status_code == 200
        assert 'serverInfo' in initialized.json()['result']
        headers['MCP-Protocol-Version'] = initialized.json()['result']['protocolVersion']
        listed = client.post('/mcp', headers=headers, json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
        assert listed.status_code == 200
        assert tool in {t['name'] for t in listed.json()['result']['tools']}
        called = client.post('/mcp', headers=headers, json={'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                             'params': {'name': tool, 'arguments': args}})
        assert called.status_code == 200
        result = called.json()['result']
        assert not result.get('isError')
        assert result['structuredContent']['status'] in {'ok', 'unavailable'}
