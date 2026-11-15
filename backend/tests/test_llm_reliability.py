import pytest
from pydantic import BaseModel

from app import llm
from app.config import Settings
from app.errors import public_error


class Output(BaseModel):
    answer: str


class WrappedBusyError(Exception):
    pass


def test_wrapped_google_503_is_identified_without_exposing_provider_body():
    error = WrappedBusyError("503 UNAVAILABLE. {'message':'high demand', 'api_key':'secret'}")
    assert public_error(error)['code'] == 'provider_busy'
    assert 'secret' not in str(public_error(error))


def test_primary_outage_uses_configured_fallback(monkeypatch):
    monkeypatch.setattr(llm, 'get_settings', lambda: Settings(gemini_model='primary', gemini_fallback_model='fallback'))
    monkeypatch.setattr(llm.time, 'sleep', lambda _: None)
    calls = []

    class Model:
        def __init__(self, name):
            self.name = name

        def invoke(self, messages):
            calls.append(self.name)
            if self.name == 'primary':
                raise WrappedBusyError('503 UNAVAILABLE. high demand')
            return Output(answer='A real model response')

    monkeypatch.setattr(llm, 'structured_model', lambda name, *args, **kwargs: Model(name))
    assert llm.invoke_structured(Output, []).answer == 'A real model response'
    assert calls == ['primary', 'primary', 'fallback']


async def test_async_outage_recovers_on_fallback(monkeypatch):
    monkeypatch.setattr(llm, 'get_settings', lambda: Settings(gemini_model='primary', gemini_fallback_model='fallback'))
    calls = []

    async def no_wait(_):
        pass

    monkeypatch.setattr(llm.asyncio, 'sleep', no_wait)

    class Model:
        def __init__(self, name):
            self.name = name

        async def ainvoke(self, messages):
            calls.append(self.name)
            if self.name == 'primary':
                raise WrappedBusyError('503 UNAVAILABLE. high demand')
            return Output(answer='Saved itinerary')

    monkeypatch.setattr(llm, 'structured_model', lambda name, *args, **kwargs: Model(name))
    assert (await llm.ainvoke_structured(Output, [])).answer == 'Saved itinerary'
    assert calls == ['primary', 'primary', 'fallback']


def test_quota_error_is_not_retried_across_models(monkeypatch):
    monkeypatch.setattr(llm, 'get_settings', lambda: Settings(gemini_model='primary', gemini_fallback_model='fallback', gemini_fallback_api_key='backup-key'))
    calls = []

    class Model:
        def invoke(self, messages):
            calls.append('primary')
            raise WrappedBusyError('429 RESOURCE_EXHAUSTED. quota')

    monkeypatch.setattr(llm, 'structured_model', lambda *args, **kwargs: Model())
    with pytest.raises(WrappedBusyError):
        llm.invoke_structured(Output, [])
    assert calls == ['primary']


def test_sync_fallback_key_preserves_primary_and_same_model(monkeypatch):
    settings = Settings(gemini_model='primary-model', gemini_api_key='primary-key',
                        gemini_fallback_model='', gemini_fallback_api_key='backup-key')
    monkeypatch.setattr(llm, 'get_settings', lambda: settings)
    monkeypatch.setattr(llm.time, 'sleep', lambda _: None)
    calls = []

    class Model:
        def __init__(self, key):
            self.key = key

        def invoke(self, messages):
            if self.key == 'primary-key':
                raise WrappedBusyError('503 UNAVAILABLE')
            return Output(answer='Recovered')

    def factory(name, schema, tokens, *, api_key):
        calls.append((name, api_key))
        return Model(api_key)

    monkeypatch.setattr(llm, 'structured_model', factory)
    assert llm.invoke_structured(Output, []).answer == 'Recovered'
    assert calls == [('primary-model', 'primary-key'), ('primary-model', 'primary-key'), ('primary-model', 'backup-key')]
    assert settings.gemini_api_key == 'primary-key'


@pytest.mark.parametrize('max_tokens, primary_calls', [(2500, 2), (12000, 1)])
async def test_async_key_fallback_is_not_deduplicated_by_model(monkeypatch, max_tokens, primary_calls):
    monkeypatch.setattr(llm, 'get_settings', lambda: Settings(gemini_model='same-model', gemini_api_key='primary-key',
                        gemini_fallback_model='', gemini_fallback_api_key='backup-key'))
    calls = []

    async def no_wait(_):
        pass

    monkeypatch.setattr(llm.asyncio, 'sleep', no_wait)

    class Model:
        def __init__(self, key):
            self.key = key

        async def ainvoke(self, messages):
            if self.key == 'primary-key':
                raise TimeoutError()
            return Output(answer='Recovered')

    def factory(name, schema, tokens, *, api_key):
        calls.append(api_key)
        return Model(api_key)

    monkeypatch.setattr(llm, 'structured_model', factory)
    assert (await llm.ainvoke_structured(Output, [], max_tokens=max_tokens)).answer == 'Recovered'
    assert calls == ['primary-key'] * primary_calls + ['backup-key']
