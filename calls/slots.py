from __future__ import annotations

from datetime import date, datetime, time, timedelta

from core.timeutils import tz

SLOT_TIMES = [(12, 0), (12, 30), (13, 0), (13, 30), (14, 0), (14, 30)]
BUFFER_HOURS = 3
_EXCLUDED_WEEKDAYS = (2, 5, 6)  # Wednesday, Saturday, Sunday


def is_business_day(day: date) -> bool:
    return day.weekday() not in _EXCLUDED_WEEKDAYS


def day_slots(day: date, tzinfo) -> list[datetime]:
    return [datetime.combine(day, time(h, m), tzinfo=tzinfo) for h, m in SLOT_TIMES]


def next_two_slots(
    now: datetime,
    unavailable: set[datetime],
    search_days_limit: int = 30,
) -> tuple[datetime, datetime] | None:
    """Первые два свободных слота одного дня: будни кроме среды, не раньше
    now + BUFFER_HOURS, минус занятые/уже предложенные слоты из `unavailable`.
    None, если ничего не нашли за `search_days_limit` дней.

    Дата и время слотов всегда считаются в Europe/Moscow, независимо от таймзоны входного
    `now` — `.date()` сам по себе не конвертирует таймзону, поэтому `now` явно приводится
    к московской перед вычислением "сегодня" (иначе near-midnight UTC даёт неверный день,
    а слоты 12:00-14:30 генерировались бы в чужом часовом поясе)."""
    cutoff = now + timedelta(hours=BUFFER_HOURS)
    day = now.astimezone(tz()).date()
    for _ in range(search_days_limit):
        if is_business_day(day):
            candidates = [
                slot
                for slot in day_slots(day, tz())
                if slot >= cutoff and slot not in unavailable
            ]
            if len(candidates) >= 2:
                return candidates[0], candidates[1]
        day += timedelta(days=1)
    return None
