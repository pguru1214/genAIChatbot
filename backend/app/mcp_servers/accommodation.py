"""Sourced accommodation and dining searches using the existing bounded adapter."""
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from app.config import get_settings
from app.food_stays import Lookup, ServicePreferences
from app.mcp_servers.common import Destination, READ_ONLY, ToolResult, execute

Radius = Annotated[int, Field(ge=100, le=10000)]
StayType = Literal['any', 'hotel', 'guest_house', 'hostel', 'apartment']


async def search_places(destination: str, kind: str, preferences: ServicePreferences, radius: int) -> ToolResult:
    if not get_settings().geoapify_api_key:
        return ToolResult(status='unavailable', notices=['Configure GEOAPIFY_API_KEY to search accommodation and dining.'])

    async def operation():
        lookup = Lookup(get_settings().geoapify_api_key)
        point = await lookup.town(destination)
        places = await lookup.places(point, kind, preferences, radius=radius)
        return {'destination': destination, 'point': point, 'places': places,
                'provider': 'Geoapify / OpenStreetMap',
                'attribution': 'Powered by Geoapify; © OpenStreetMap contributors',
                'attribution_url': 'https://www.openstreetmap.org/copyright',
                'notice': 'Listed venues only. Ratings, prices, room availability and opening/check-in times are not verified.'}
    return await execute(operation)


def create_server(**settings) -> FastMCP:
    server = FastMCP('TripWeave Hotels and Accommodation', instructions=(
        'Search Indian accommodation and restaurants using sourced listings. Prefer city, state, India '
        'for unambiguous searches. Results are suggestions, not confirmed rooms, prices or bookings. '
        'Preserve attribution, timestamps and provider notices.'), **settings)

    @server.tool(annotations=READ_ONLY)
    async def search_stays(destination: Destination, stay_preference: StayType = 'any',
                            accessibility: bool = False, radius_m: Radius = 3000) -> ToolResult:
        """Find up to three sourced nearby stays; filter by accommodation type and wheelchair listing."""
        return await search_places(destination, 'stay', ServicePreferences(
            stay_preference=stay_preference, accessibility=accessibility), radius_m)

    @server.tool(annotations=READ_ONLY)
    async def search_restaurants(destination: Destination, dietary: Literal['any', 'vegetarian', 'vegan'] = 'any',
                                  cuisine: Annotated[str, Field(max_length=100)] = '',
                                  accessibility: bool = False, radius_m: Radius = 3000) -> ToolResult:
        """Find up to three sourced restaurants/cafes matching listed dietary, cuisine and access preferences."""
        return await search_places(destination, 'meal', ServicePreferences(
            dietary=dietary, cuisine=cuisine, accessibility=accessibility), radius_m)

    return server
