"""Useful public failures without exposing provider responses or credentials."""
import httpx
import re

from app.tools import DestinationNeedsClarification


class ModelResponseError(ValueError):
    """The model returned no usable structured response."""


def provider_status(error: Exception) -> int | None:
    """LangChain can wrap Google's API error, losing its .code attribute."""
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, httpx.HTTPStatusError):
            return current.response.status_code
        code = getattr(current, 'code', None)
        if isinstance(code, (int, str)) and str(code).isdigit():
            return int(code)
        # Inspect only a status token; never return/log the provider's raw text.
        match = re.search(r'\b(400|401|403|404|408|429|500|502|503|504)\s+(?:UNAVAILABLE|RESOURCE_EXHAUSTED|INTERNAL|NOT_FOUND|PERMISSION_DENIED|UNAUTHENTICATED|DEADLINE_EXCEEDED)\b', str(current))
        if match:
            return int(match[1])
        current = current.__cause__ or current.__context__
    return None


def public_error(error: Exception) -> dict:
    if isinstance(error, DestinationNeedsClarification):
        return {'code': 'destination_clarification', 'field': 'destination',
                'message': str(error) + (' Options: ' + '; '.join(error.choices) if error.choices else ''),
                'choices': error.choices, 'retryable': False}
    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        return {'code': 'provider_timeout', 'message': 'A travel or AI service timed out. Your request did not finish. Please retry shortly.', 'retryable': True}
    if isinstance(error, httpx.TransportError):
        return {'code': 'provider_connection', 'message': 'Could not reach a travel service. Check the backend internet connection and retry.', 'retryable': True}
    status = provider_status(error)
    if status in {500, 502, 503, 504}:
        return {'code': 'provider_busy', 'message': 'The AI service is temporarily overloaded. Your saved details are safe. Please retry shortly; changing a valid date will not fix a service outage.', 'retryable': True}
    if isinstance(error, ModelResponseError):
        return {'code': 'model_response_invalid', 'message': 'The AI service returned an incomplete answer. Your details are saved; please retry the saved turn.', 'retryable': True}
    if status == 429:
        return {'code': 'provider_quota', 'message': 'A service rate limit or API quota was reached. Check your Gemini quota and retry later.', 'retryable': True}
    if status in {401, 403}:
        return {'code': 'provider_access', 'message': 'A service denied access. Check the configured API key and permissions, then restart the backend if you change .env.', 'retryable': False}
    if status == 404:
        return {'code': 'provider_not_found', 'message': 'A configured model or service was not found. Check GEMINI_MODEL and its availability for your account.', 'retryable': False}
    return {'code': 'workflow_failed', 'message': 'The request could not finish. Retry or update your trip details. Reference the run ID when reporting this problem.', 'retryable': True}
