from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from calls.slots import next_two_slots

MSK = ZoneInfo("Europe/Moscow")
UTC = ZoneInfo("UTC")


def msk(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=MSK)


def test_happy_path_morning_send():
    result = next_two_slots(now=msk(24, 9, 0), unavailable=set())
    assert result == (msk(24, 12, 0), msk(24, 12, 30))


def test_buffer_excludes_early_slots():
    # ТЗ: письмо в 11:00 -> ближайшее время 14:00
    result = next_two_slots(now=msk(24, 11, 0), unavailable=set())
    assert result == (msk(24, 14, 0), msk(24, 14, 30))


def test_buffer_boundary_is_inclusive():
    result = next_two_slots(now=msk(24, 10, 0), unavailable=set())
    assert result == (msk(24, 13, 0), msk(24, 13, 30))


def test_no_slots_left_today_moves_to_next_business_day():
    result = next_two_slots(now=msk(24, 12, 1), unavailable=set())
    assert result == (msk(25, 12, 0), msk(25, 12, 30))


def test_wednesday_is_fully_skipped():
    result = next_two_slots(now=msk(26, 9, 0), unavailable=set())
    assert result == (msk(27, 12, 0), msk(27, 12, 30))


def test_weekend_is_skipped():
    result = next_two_slots(now=msk(29, 9, 0), unavailable=set())
    assert result == (msk(31, 12, 0), msk(31, 12, 30))


def test_already_offered_slots_are_excluded():
    unavailable = {msk(24, 12, 0), msk(24, 12, 30)}
    result = next_two_slots(now=msk(24, 9, 0), unavailable=unavailable)
    assert result == (msk(24, 13, 0), msk(24, 13, 30))


def test_day_with_single_free_slot_is_skipped_entirely():
    unavailable = {msk(24, 12, 0), msk(24, 12, 30), msk(24, 13, 0), msk(24, 13, 30), msk(24, 14, 0)}
    result = next_two_slots(now=msk(24, 9, 0), unavailable=unavailable)
    assert result == (msk(25, 12, 0), msk(25, 12, 30))


def test_utc_now_near_midnight_msk_uses_moscow_calendar_date():
    # 2026-08-24 22:00 UTC == 2026-08-25 01:00 MSK — разные календарные даты. Слоты обязаны
    # считаться по МОСКОВСКОЙ дате (25 августа, вторник), а не по "сырой" дате объекта datetime
    # (24 августа, понедельник) — .date() сам по себе НЕ делает конвертацию таймзоны.
    result = next_two_slots(now=datetime(2026, 8, 24, 22, 0, tzinfo=UTC), unavailable=set())
    assert result == (msk(25, 12, 0), msk(25, 12, 30))


def test_fully_booked_window_returns_none():
    unavailable = set()
    day = 24
    for _ in range(40):
        for hour, minute in [(12, 0), (12, 30), (13, 0), (13, 30), (14, 0), (14, 30)]:
            unavailable.add(msk(day, hour, minute))
        day += 1
        if day > 31:
            break
    result = next_two_slots(now=msk(24, 9, 0), unavailable=unavailable, search_days_limit=5)
    assert result is None
