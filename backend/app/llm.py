"""Bounded retries and an explicitly configured Gemini fallback model."""
import asyncio
import time
import httpx

from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import ValidationError

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
    return ChatGoogleGenerativeAI(model=model_name, api_key=get_settings().gemini_api_key,
        timeout=18, max_retries=0, max_output_tokens=max_tokens).with_structured_output(schema)


def checked_response(response, schema):
    if response is None:
        raise ModelResponseError('No structured model response')
    try:
        return response if isinstance(response, schema) else schema.model_validate(response)
    except ValidationError:
        raise ModelResponseError('Invalid structured model response') from None


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
    attempts = model_attempts()
    for index, name in enumerate(attempts):
        try:
            return checked_response(await structured_model(name, schema, max_tokens).ainvoke(messages), schema)
        except Exception as error:
            if index == len(attempts) - 1 or not transient(error):
                raise
            await asyncio.sleep(index + 1)
