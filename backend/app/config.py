from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    app_mode: Literal['demo', 'live'] = 'demo'
    gemini_api_key: str = ''
    gemini_model: str = ''
    database_url: str = 'sqlite:///./tripweave.db'
    cors_origins: list[str] = ['http://localhost:5173', 'http://127.0.0.1:5173']


@lru_cache
def get_settings() -> Settings:
    return Settings()
