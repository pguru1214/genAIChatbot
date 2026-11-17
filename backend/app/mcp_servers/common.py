"""Shared result contracts, input bounds and safe provider failures."""
import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

import httpx
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from app.geoapify import FreeQuotaExceeded
from app.tourism import DestinationNeedsClarification

Destination = Annotated[str, Field(min_length=2, max_length=200, pattern=r'.*\S.*')]
Latitude = Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)]
Longitude = Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]
Days = Annotated[int, Field(ge=1, le=7)]
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)


class ToolResult(BaseModel):
    status: Literal['ok', 'unavailable', 'needs_clarification'] = 'ok'
    retrieved_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    data: dict[str, Any] = Field(default_factory=dict)
    notices: list[str] = Field(default_factory=list)


async def execute(operation: Callable[[], Awaitable[dict]], *, timeout: float = 45) -> ToolResult:
    """Never serialize raw HTTP exceptions: their URLs can contain provider keys."""
    try:
        async with asyncio.timeout(timeout):
            data = await operation()
        return ToolResult(data=data)
    except DestinationNeedsClarification as error:
        return ToolResult(status='needs_clarification', data={'field': error.field, 'choices': error.choices},
                          notices=[str(error)])
    except FreeQuotaExceeded:
        return ToolResult(status='unavailable', notices=['The local/provider free lookup allowance was reached. Try again later.'])
    except (TimeoutError, httpx.TimeoutException):
        return ToolResult(status='unavailable', notices=['The provider lookup timed out. No missing facts were inferred.'])
    except (httpx.HTTPError, OSError):
        return ToolResult(status='unavailable', notices=['The provider is unavailable. Try again later.'])
    except (ValueError, KeyError, TypeError):
        return ToolResult(status='unavailable', notices=['The lookup could not be verified. Refine the destination or try again later.'])
    except Exception:
        # Database/adapter failures must not expose connection strings or keys.
        # Cancellation still propagates (CancelledError is a BaseException).
        return ToolResult(status='unavailable', notices=['The lookup could not finish. Try again later.'])
