"""Bounded retries and an explicitly configured Gemini fallback model."""
import asyncio
import time
import json
import httpx

from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import ValidationError
from langchain_core.messages import SystemMessage, AIMessage

from app.config import get_settings
from app.errors import ModelResponseError, provider_status


def model_attempts():
    settings = get_settings()
    models = [settings.gemini_model]
    if settings.gemini_fallback_model and settings.gemini_fallback_model not in models:
        models.append(settings.gemini_fallback_model)
    # Primary: one retry. Optional fallback: one attempt. No quota/auth bypass.
    return [models[0], *models]


def transient(error):
    return provider_status(error) in {408, 500, 502, 503, 504} or isinstance(error, (TimeoutError, httpx.TimeoutException, ModelResponseError))


def structured_model(model_name, schema, max_tokens):
    wire_schema = schema
    if max_tokens > 4000:
        # Nested bounded arrays can make Gemini's constrained decoder reject a
        # valid JSON schema with HTTP 400. Keep the wire shape simple; the full
        # Pydantic schema and request-specific rules still validate every result.
        wire_schema = provider_schema(schema.model_json_schema(), getattr(schema, 'allowed_source_ids', None))
    return ChatGoogleGenerativeAI(model=model_name, api_key=get_settings().gemini_api_key,
        timeout=60 if max_tokens >= 12000 else 35 if max_tokens > 4000 else 18,
        max_retries=0, max_output_tokens=max_tokens).with_structured_output(wire_schema)


def provider_schema(value, allowed_sources=None):
    if isinstance(value, list):
        return [provider_schema(v, allowed_sources) for v in value]
    if isinstance(value, dict):
        result = {k: provider_schema(v, allowed_sources) for k, v in value.items()
                  if k not in {'minLength', 'maxLength', 'minItems', 'maxItems', 'minimum', 'maximum', 'default'}}
        if allowed_sources and 'source_ids' in result and isinstance(result['source_ids'], dict):
            result['source_ids']['items'] = {'type': 'string', 'enum': allowed_sources}
        return result
    return value


def checked_response(response, schema):
    if response is None:
        raise ModelResponseError('No structured model response', reason='empty')
    try:
        return response if isinstance(response, schema) else schema.model_validate(response)
    except ValidationError as error:
        failure = ModelResponseError('Invalid structured model response')
        failure.feedback = '; '.join(str(e['loc']) + ': ' + e['msg'] for e in error.errors(include_input=False, include_url=False))[:1500]
        failure.response_data = response
        raise failure from None


def invoke_structured(schema, messages, max_tokens=2500):
    attempts = model_attempts()
    for index, name in enumerate(attempts):
        try:
            return checked_response(structured_model(name, schema, max_tokens).invoke(messages), schema)
        except Exception as error:
            if index == len(attempts) - 1 or not transient(error):
                raise
            time.sleep(index + 1)


async def ainvoke_structured(schema, messages, max_tokens=2500):
    messages = list(messages)
    attempts = model_attempts()
    if max_tokens >= 12000:
        # Long itineraries get time to finish, with at most two requests total.
        distinct = list(dict.fromkeys(attempts))
        attempts = distinct if len(distinct) > 1 else attempts[:2]
    for index, name in enumerate(attempts):
        try:
            return checked_response(await structured_model(name, schema, max_tokens).ainvoke(messages), schema)
        except Exception as error:
            if index == len(attempts) - 1 or not transient(error):
                raise
            if isinstance(error, ModelResponseError) and getattr(error, 'feedback', ''):
                messages.append(AIMessage(content=json.dumps(error.response_data, default=str)))
                messages.append(SystemMessage(content='The previous structured response failed backend validation. Correct these constraints: ' + error.feedback))
            await asyncio.sleep(index + 1)
