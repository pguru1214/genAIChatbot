"""Shared planning defaults; explicit preferences always win."""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def clock_minutes(value):
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
        raise ValueError('Use a 24-hour time such as 10:00 or 18:00')
    hour, minute = map(int, value.split(':'))
    return hour * 60 + minute


def planning_defaults(details):
    result = dict(details)
    local_date = datetime.now(ZoneInfo(result.get('timezone') or 'Asia/Kolkata')).date()
    defaults = {'start_date': (local_date + timedelta(days=7)).isoformat(), 'budget': '50000',
                'currency': 'INR', 'day_start': '10:00', 'day_end': '18:00',
                'interests': 'general sightseeing', 'companions': 'not specified'}
    applied = []
    for name, value in defaults.items():
        if result.get(name) in (None, ''):
            result[name] = value
            applied.append(name)
    return result, applied
