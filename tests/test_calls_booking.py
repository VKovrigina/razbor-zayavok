from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from calls import booking
from calls.booking import find_free_pair

MSK = ZoneInfo("Europe/Moscow")


def msk(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=MSK)


def _stub_is_slot_free(monkeypatch, busy_starts: set):
    monkeypatch.setattr(
        booking.calendar_client, "is_slot_free", lambda busy_calendar, start, end: start not in busy_starts
    )


def test_returns_first_pair_when_calendar_fully_free(monkeypatch):
    _stub_is_slot_free(monkeypatch, busy_starts=set())
    result = find_free_pair(now=msk(24, 9, 0), reserved=set(), busy_calendar=object())
    assert result == (msk(24, 12, 0), msk(24, 12, 30))


def test_skips_slot_busy_in_calendar_but_not_in_db(monkeypatch):
    _stub_is_slot_free(monkeypatch, busy_starts={msk(24, 12, 0)})
    result = find_free_pair(now=msk(24, 9, 0), reserved=set(), busy_calendar=object())
    assert result == (msk(24, 12, 30), msk(24, 13, 0))


def test_skips_both_slots_busy_in_calendar(monkeypatch):
    _stub_is_slot_free(monkeypatch, busy_starts={msk(24, 12, 0), msk(24, 12, 30)})
    result = find_free_pair(now=msk(24, 9, 0), reserved=set(), busy_calendar=object())
    assert result == (msk(24, 13, 0), msk(24, 13, 30))


def test_returns_none_when_everything_busy(monkeypatch):
    all_day_slots = {msk(24, h, m) for h, m in [(12, 0), (12, 30), (13, 0), (13, 30), (14, 0), (14, 30)]}
    _stub_is_slot_free(monkeypatch, busy_starts=all_day_slots)
    result = find_free_pair(now=msk(24, 9, 0), reserved=set(), busy_calendar=object(), search_days_limit=1)
    assert result is None
