from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator
from app.planning import clock_minutes


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    destination: str = Field(min_length=1, max_length=200)
    origin: str | None = Field(default=None, min_length=1, max_length=200)
    day_start: str = '10:00'
    day_end: str = '18:00'
    defaulted_fields: list[str] = Field(default_factory=list)
    days: int = Field(default=3, ge=1, le=7)
    start_date: date | None = None
    timezone: str = 'Asia/Kolkata'
    intent: Literal['auto', 'research', 'plan', 'email', 'calendar'] = 'auto'
    trip_id: str | None = None
    budget: str = ''
    currency: str = ''
    interests: str = ''
    companions: str = ''

    @field_validator('day_start', 'day_end')
    @classmethod
    def valid_clock(cls, value):
        clock_minutes(value)
        return value

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
        if clock_minutes(self.day_end) - clock_minutes(self.day_start) < 60:
            raise ValueError('Allow at least one hour between daily start and finish')
        if self.intent in {'email', 'calendar'} and not self.trip_id:
            raise ValueError('Select a saved trip before preparing an action')
        return self
