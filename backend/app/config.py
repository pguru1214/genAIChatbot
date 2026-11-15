from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[1] / '.env', extra='ignore')
    app_mode: Literal['demo', 'live'] = 'demo'
    gemini_api_key: str = ''
    gemini_fallback_api_key: str = ''
    gemini_model: str = ''
    gemini_fallback_model: str = ''
    geoapify_api_key: str = ''
    geoapify_daily_credit_limit: int = 2400
    database_url: str = 'sqlite:///./tripweave.db'
    cors_origins: list[str] = ['http://localhost:5173', 'http://127.0.0.1:5173']
    public_deployment: bool = False
    deployment_access_password: str = ''
    session_signing_key: str = ''
    frontend_dist: str = ''
    railcore_api_key: str = ''
    travelpayouts_api_token: str = ''


@lru_cache
def get_settings() -> Settings:
    return Settings()
