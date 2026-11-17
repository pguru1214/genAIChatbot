"""Destination context, weather and transport tools; no LLM or booking calls."""
from datetime import date
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from app import tools, transport
from app.mcp_servers.common import Days, Destination, Latitude, Longitude, READ_ONLY, ToolResult, execute


def create_server(**settings) -> FastMCP:
    server = FastMCP('TripWeave Travel Recommendations', instructions=(
        'India travel research tools. Resolve ambiguous destinations first. Combine results with the '
        'Attractions and Accommodation servers to plan trips. Preserve source links, notices and '
        'timestamps. Never treat cached fares as confirmed inventory. No bookings are performed.'), **settings)

    @server.tool(annotations=READ_ONLY)
    async def resolve_destination(destination: Destination) -> ToolResult:
        """Resolve an Indian destination; ambiguous names return clarification choices."""
        return await execute(lambda: tools.resolve_destination.ainvoke({'destination': destination}))

    @server.tool(annotations=READ_ONLY)
    async def get_destination_summary(destination: Destination) -> ToolResult:
        """Get a Wikipedia summary and source URL after verifying the Indian destination."""
        async def operation():
            location = await tools.resolve_destination.ainvoke({'destination': destination})
            summary = await tools.get_destination_summary.ainvoke({'destination': ', '.join(
                str(location[k]) for k in ('name', 'admin1', 'country') if location.get(k))})
            return {'location': location, **summary}
        return await execute(operation)

    @server.tool(annotations=READ_ONLY)
    async def get_weather(latitude: Latitude, longitude: Longitude, start_date: date, days: Days = 3) -> ToolResult:
        """Fetch up to seven days of weather within the provider's 16-day forecast window."""
        result = await execute(lambda: tools.get_weather.ainvoke({
            'latitude': latitude, 'longitude': longitude, 'start_date': start_date.isoformat(), 'days': days}))
        result.data['source_url'] = 'https://open-meteo.com/'
        if result.data.get('available') is False:
            result.status = 'unavailable'
            result.notices.append(result.data['reason'])
        return result

    @server.tool(annotations=READ_ONLY)
    async def search_transport(mode: Literal['flight', 'train', 'bus'], origin: Destination,
                               destination: Destination, journey_date: date,
                               passengers: Annotated[int, Field(ge=1, le=6)] = 1,
                               origin_code: Annotated[str | None, Field(max_length=8)] = None,
                               destination_code: Annotated[str | None, Field(max_length=8)] = None) -> ToolResult:
        """Search transport using configured providers; retain demo/disconnected/cached-fare notices."""
        request = transport.SearchRequest(mode=mode, origin=origin, destination=destination, date=journey_date,
                                          passengers=passengers, origin_code=origin_code, destination_code=destination_code)
        return await execute(lambda: transport.search_transport(request))

    return server
