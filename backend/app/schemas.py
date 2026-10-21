from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    destination: str = Field(min_length=1, max_length=200)
    days: int = Field(default=3, ge=1, le=7)
    start_date: date | None = None
    timezone: str = 'Asia/Kolkata'
    intent: Literal['auto', 'research', 'plan', 'email', 'calendar'] = 'auto'
    trip_id: str | None = None

    @field_validator('message', 'destination')
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('Must not be blank')
        return value.strip()

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise ValueError('Use a valid IANA time zone')
        return value

    @model_validator(mode='after')
    def action_needs_trip(self):
        if self.intent in {'email', 'calendar'} and not self.trip_id:
            raise ValueError('Select a saved trip before preparing an action')
        return self
