import json
import httpx
import pytest

from app.config import Settings
from app.places import geoapify_places, wikipedia_places
import app.tools as tools


def wiki_result():
    return {'query': {'pages': {
        '1': {'title': 'Historic Museum', 'index': 1, 'extract': 'A museum of city history.', 'coordinates': [{'lat': 35, 'lon': 135}], 'categories': [{'title': 'Category:Museums in Kyoto'}]},
        '2': {'title': 'Central Station', 'index': 0, 'categories': [{'title': 'Category:Railway stations in Kyoto'}]},
        '3': {'title': 'Kyoto', 'categories': [{'title': 'Category:Cities and towns in Japan'}, {'title': 'Category:Tourist attractions in Japan'}]},
        '4': {'title': 'Siege of Sanjō Palace', 'categories': [{'title': 'Category:Palaces'}]},
        '5': {'title': 'Shōkoku-ji', 'index': 2, 'categories': [{'title': 'Category:Buddhist temples in Kyoto'}]},
    }}}


async def test_wikipedia_filters_events_and_city_pages_and_preserves_sources():
    async def fetch(url, params):
        assert params['generator'] == 'geosearch'
        assert params['ggscoord'] == '35.0|135.0'
        assert params['ggsradius'] == 8000
        return wiki_result()

    result = await wikipedia_places(35, 135, fetch)
    assert [p['name'] for p in result['places']] == ['Historic Museum', 'Shōkoku-ji']
    assert result['places'][1]['url'].endswith('Sh%C5%8Dkoku-ji')
    assert all(p['opening_hours'] is None for p in result['places'])
    assert result['provider'] == 'Wikipedia nearby places'


async def test_geoapify_normalizes_places_without_leaking_key():
    async def fetch(url, params):
        assert params['apiKey'] == 'private-key'
        assert params['filter'] == 'circle:135.0,35.0,8000'
        return {'features': [{'properties': {'name': 'Museum', 'categories': ['entertainment.museum'], 'formatted': 'Kyoto'}, 'geometry': {'coordinates': [135.1, 35.1]}}, {'properties': {}, 'geometry': {}}]}

    result = await geoapify_places(35, 135, 'private-key', fetch)
    assert len(result['places']) == 1
    assert result['places'][0]['name'] == 'Museum'
    assert result['places'][0]['latitude'] == 35.1
    assert result['provider'] == 'Geoapify Places'
    assert 'private-key' not in json.dumps(result)
    assert 'OpenStreetMap' in result['attribution']


async def test_no_key_uses_wikipedia_without_touching_overpass(monkeypatch):
    monkeypatch.setattr(tools, 'get_settings', lambda: Settings(geoapify_api_key=''))

    async def fetch(url, params):
        assert url == 'https://en.wikipedia.org/w/api.php'
        return wiki_result()

    monkeypatch.setattr(tools, 'fetch', fetch)
    result = await tools.get_visitor_places.ainvoke({'latitude': 35, 'longitude': 135})
    assert result['provider'] == 'Wikipedia nearby places'
    assert len(result['places']) == 2


async def test_geoapify_failure_falls_back_without_exposing_key(monkeypatch):
    monkeypatch.setattr(tools, 'get_settings', lambda: Settings(geoapify_api_key='private-key'))
    calls = []

    async def fetch(url, params):
        calls.append(url)
        if 'geoapify' in url:
            request = httpx.Request('GET', url, params=params)
            raise httpx.HTTPStatusError('Forbidden private-key', request=request, response=httpx.Response(403, request=request))
        return wiki_result()

    monkeypatch.setattr(tools, 'fetch', fetch)
    result = await tools.get_visitor_places.ainvoke({'latitude': 35, 'longitude': 135})
    assert len(calls) == 2
    assert result['provider'] == 'Wikipedia nearby places'
    assert result['notices']
    assert 'private-key' not in json.dumps(result)


async def test_research_preserves_provider_identity_and_named_places(monkeypatch):
    monkeypatch.setattr(tools, 'get_settings', lambda: Settings(geoapify_api_key=''))

    async def fetch(url, params):
        assert 'overpass' not in url
        if 'geocoding' in url:
            return {'results': [{'name': 'Testcity', 'country': 'India', 'latitude': 26, 'longitude': 75}]}
        if params.get('generator') == 'geosearch':
            return wiki_result()
        return {'query': {'pages': {'1': {'title': 'Kyoto', 'extract': 'A city in Japan.', 'fullurl': 'https://en.wikipedia.org/wiki/Kyoto'}}}}

    monkeypatch.setattr(tools, 'fetch', fetch)
    result = await tools.collect_evidence({'destination': 'Testcity, India', 'days': 3}, False)
    places = next(e for e in result['evidence'] if e['id'] == 'source-2')
    assert places['provider'] == 'Wikipedia nearby places'
    assert places['data']['places'][0]['name'] == 'Historic Museum'
    assert result['errors'] == []


@pytest.mark.parametrize('lat,lon', [(91, 135), (35, 181), (float('nan'), 135)])
async def test_bad_coordinates_never_reach_provider(lat, lon):
    async def fetch(*args):
        raise AssertionError('Invalid coordinates must not reach a provider')

    with pytest.raises(ValueError):
        await wikipedia_places(lat, lon, fetch)
