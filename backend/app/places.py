"""Normalized visitor-place data from Geoapify or public Wikipedia articles."""
import math
import re
from urllib.parse import quote


WIKIPEDIA_API = 'https://en.wikipedia.org/w/api.php'
GEOAPIFY_API = 'https://api.geoapify.com/v2/places'
VISITOR_PLACE = re.compile(r'\b(museums?|temples?|shrines?|palaces?|castles?|forts?|gardens?|parks?|monuments?|landmarks?|tourist attractions?|art galleries|heritage sites?|historic buildings|historic sites)\b', re.I)
NON_VISITOR = re.compile(r'Category:(?:Cities(?: and towns)? in|Towns in|Wards of|Railway stations|People from|Universities in|Schools in|Sieges|Battles|Conflicts|Massacres)', re.I)
HISTORICAL_EVENT = re.compile(r'^(?:Siege of|Battle of|List of|Attack on|Bombing of)\b', re.I)


def coordinates(latitude, longitude):
    lat, lon = float(latitude), float(longitude)
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError('Invalid coordinates')
    return lat, lon


async def wikipedia_places(latitude, longitude, fetch):
    lat, lon = coordinates(latitude, longitude)
    data = await fetch(WIKIPEDIA_API, {
        'action': 'query', 'generator': 'geosearch', 'ggscoord': f'{lat}|{lon}',
        'ggsradius': 8000, 'ggslimit': 100, 'ggsnamespace': 0,
        'prop': 'extracts|info|coordinates|categories', 'exintro': 1,
        'explaintext': 1, 'exchars': 600, 'inprop': 'url', 'cllimit': 30, 'format': 'json',
    })
    if data.get('error'):
        raise ValueError('Wikipedia nearby-place lookup could not finish')
    places = []
    pages = sorted(data.get('query', {}).get('pages', {}).values(), key=lambda p: p.get('index', 999))
    for page in pages:
        title = page.get('title', '')
        categories = ' '.join(c.get('title', '') for c in page.get('categories', []))
        if page.get('ns', 0) != 0 or not title or NON_VISITOR.search(categories) or HISTORICAL_EVENT.search(title):
            continue
        kind = VISITOR_PLACE.search(title + ' ' + categories)
        if not kind:
            continue
        location = next(iter(page.get('coordinates', [])), {})
        places.append({'name': title, 'type': kind[0].lower(),
            'description': page.get('extract', '')[:600],
            'latitude': location.get('lat'), 'longitude': location.get('lon'),
            'url': 'https://en.wikipedia.org/wiki/' + quote(title.replace(' ', '_'), safe=''),
            'opening_hours': None})
        if len(places) == 12:
            break
    return {'provider': 'Wikipedia nearby places', 'places': places,
        'url': places[0]['url'] if places else 'https://en.wikipedia.org/wiki/Special:Nearby',
        'limitations': 'Nearby articles filtered for visitor places. Coverage is incomplete; opening hours, admission prices and booking availability are not verified.',
        'attribution': 'Wikipedia contributors, CC BY-SA',
        'attribution_url': 'https://en.wikipedia.org/wiki/Wikipedia:Copyrights'}


async def geoapify_places(latitude, longitude, api_key, fetch):
    lat, lon = coordinates(latitude, longitude)
    data = await fetch(GEOAPIFY_API, {'categories': 'tourism.sights,tourism.attraction,entertainment.museum',
        'filter': f'circle:{lon},{lat},8000', 'bias': f'proximity:{lon},{lat}',
        'limit': 12, 'apiKey': api_key})
    places = []
    for feature in data.get('features', [])[:12]:
        properties = feature.get('properties', {})
        name = properties.get('name')
        if not name:
            continue
        point = feature.get('geometry', {}).get('coordinates', [])
        place_lon = properties.get('lon', point[0] if len(point) >= 2 else None)
        place_lat = properties.get('lat', point[1] if len(point) >= 2 else None)
        if place_lat is None or place_lon is None:
            continue
        place_lat, place_lon = coordinates(place_lat, place_lon)
        places.append({'name': name, 'type': ', '.join(properties.get('categories', [])),
            'latitude': place_lat, 'longitude': place_lon,
            'address': properties.get('formatted'),
            'url': f'https://www.openstreetmap.org/?mlat={place_lat}&mlon={place_lon}#map=16/{place_lat}/{place_lon}',
            'opening_hours': None})
    return {'provider': 'Geoapify Places', 'places': places,
        'url': 'https://www.geoapify.com/places-api/',
        'limitations': 'Place listings do not verify future opening hours, current admission prices, or booking availability.',
        'attribution': 'Powered by Geoapify; © OpenStreetMap contributors',
        'attribution_url': 'https://www.openstreetmap.org/copyright'}
