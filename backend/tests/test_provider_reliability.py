import httpx
import pytest

import app.tools as tools


def mock_transport(monkeypatch, handler):
    factory = httpx.AsyncClient
    monkeypatch.setattr(tools.httpx, 'AsyncClient',
                        lambda **kwargs: factory(transport=httpx.MockTransport(handler), **kwargs))

    async def no_wait(*args):
        pass

    monkeypatch.setattr(tools.asyncio, 'sleep', no_wait)


async def test_wikipedia_identifies_project_and_retries_temporary_failure(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        assert 'https://github.com/pguru1214/genAIChatbot' in request.headers['User-Agent']
        assert request.url.params['gsrsearch'] == 'Kyoto, Japan'
        if len(requests) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={'query': {'pages': {'1': {
            'title': 'Kyoto', 'extract': 'A historic city.', 'fullurl': 'https://en.wikipedia.org/wiki/Kyoto'}}}})

    mock_transport(monkeypatch, handler)
    result = await tools.get_destination_summary.ainvoke({'destination': 'Kyoto, Japan'})
    assert result['summary'] == 'A historic city.'
    assert result['url'] == 'https://en.wikipedia.org/wiki/Kyoto'
    assert len(requests) == 2


@pytest.mark.parametrize('status,headers', [(403, {}), (429, {'Retry-After': '60'})])
async def test_fetch_does_not_retry_denied_requests_or_ignore_cooldown(monkeypatch, status, headers):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, headers=headers)

    mock_transport(monkeypatch, handler)
    with pytest.raises(httpx.HTTPStatusError):
        await tools.fetch('https://en.wikipedia.org/w/api.php', {})
    assert len(requests) == 1


async def test_overpass_recovers_from_primary_capacity_failure(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == 'POST'
        assert b'data=' in request.content
        if request.url.host == 'overpass-api.de':
            return httpx.Response(502)
        return httpx.Response(200, json={'elements': [
            {'id': 7, 'type': 'way', 'tags': {'name': 'Museum', 'tourism': 'museum'}}]})

    mock_transport(monkeypatch, handler)
    result = await tools.search_attractions.ainvoke({'latitude': 35.01, 'longitude': 135.76})
    assert result['places'][0]['url'] == 'https://www.openstreetmap.org/way/7'
    assert len(requests) == 3


async def test_overpass_200_resource_error_uses_fallback(monkeypatch):
    def handler(request):
        if request.url.host == 'overpass-api.de':
            return httpx.Response(200, json={'remark': 'runtime error: query timed out', 'elements': []})
        return httpx.Response(200, json={'elements': []})

    mock_transport(monkeypatch, handler)
    result = await tools.search_attractions.ainvoke({'latitude': 35.01, 'longitude': 135.76})
    assert result == {'places': []}


async def test_overpass_does_not_route_around_access_denial(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(403)

    mock_transport(monkeypatch, handler)
    with pytest.raises(httpx.HTTPStatusError):
        await tools.search_attractions.ainvoke({'latitude': 35.01, 'longitude': 135.76})
    assert len(requests) == 1


async def test_overpass_honors_rate_limit_before_trying_independent_fallback(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == 'overpass-api.de':
            return httpx.Response(429)
        return httpx.Response(200, json={'elements': []})

    mock_transport(monkeypatch, handler)
    assert await tools.search_attractions.ainvoke({'latitude': 35.01, 'longitude': 135.76}) == {'places': []}
    assert len(requests) == 2
