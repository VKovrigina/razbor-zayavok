from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from config import settings

_WEEKEND = (5, 6)  # Saturday, Sunday (datetime.weekday())


def tz() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def next_business_day_at_local_hour(after: datetime, hour: int) -> datetime:
    """Следующий календарный день после `after` в `hour`:00 по локальной таймзоне
    (settings.timezone), с переносом с выходных на следующий рабочий день. Возвращает
    время в UTC."""
    local_after = after.astimezone(tz())
    day = local_after.date() + timedelta(days=1)
    while day.weekday() in _WEEKEND:
        day += timedelta(days=1)
    local_dt = datetime.combine(day, time(hour=hour, minute=0), tzinfo=tz())
    return local_dt.astimezone(timezone.utc)


def next_reminder_at_iso(after: datetime | None = None) -> str:
    after = after or utcnow()
    return to_iso(next_business_day_at_local_hour(after, settings.reminder_hour_local))
