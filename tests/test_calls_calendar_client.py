from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import icalendar

from calls.calendar_client import create_event, fetch_busy_calendar, is_slot_free

MSK = ZoneInfo("Europe/Moscow")


def _ics_vevent(uid: str, start: datetime, end: datetime, summary: str = "Событие") -> str:
    return (
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}\r\n"
        f"DTEND:{end.strftime('%Y%m%dT%H%M%SZ')}\r\n"
        f"SUMMARY:{summary}\r\n"
        "END:VEVENT\r\n"
    )


def _busy_calendar(*vevent_blocks: str) -> icalendar.Calendar:
    merged = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "".join(vevent_blocks) + "END:VCALENDAR\r\n"
    return icalendar.Calendar.from_ical(merged)


class FakeEvent:
    def __init__(self, data):
        self.data = data
        self.icalendar_component = {"uid": "generated-uid"}


class FakeCalendar:
    def __init__(self, event_blocks=None):
        self._event_blocks = event_blocks or []
        self.saved_kwargs = None

    def events(self):
        return [FakeEvent(block) for block in self._event_blocks]

    def save_event(self, **kwargs):
        self.saved_kwargs = kwargs
        return FakeEvent("generated-uid")


def test_is_slot_free_true_when_calendar_has_no_events():
    busy_calendar = _busy_calendar()
    assert is_slot_free(busy_calendar, datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc), datetime(2026, 8, 24, 12, 30, tzinfo=timezone.utc)) is True


def test_is_slot_free_false_when_event_overlaps_range():
    vevent = _ics_vevent(
        "existing-1",
        datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 24, 12, 30, tzinfo=timezone.utc),
    )
    busy_calendar = _busy_calendar(vevent)
    assert is_slot_free(busy_calendar, datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc), datetime(2026, 8, 24, 12, 30, tzinfo=timezone.utc)) is False


def test_is_slot_free_true_when_event_is_on_a_different_day():
    vevent = _ics_vevent(
        "existing-2",
        datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 25, 12, 30, tzinfo=timezone.utc),
    )
    busy_calendar = _busy_calendar(vevent)
    assert is_slot_free(busy_calendar, datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc), datetime(2026, 8, 24, 12, 30, tzinfo=timezone.utc)) is True


def test_fetch_busy_calendar_merges_all_event_blocks():
    block_1 = _ics_vevent("a", datetime(2026, 8, 24, 9, 0, tzinfo=timezone.utc), datetime(2026, 8, 24, 9, 30, tzinfo=timezone.utc))
    block_2 = _ics_vevent("b", datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc), datetime(2026, 8, 24, 10, 30, tzinfo=timezone.utc))
    calendar = FakeCalendar(event_blocks=[block_1, block_2])

    merged = fetch_busy_calendar(calendar)

    uids = {str(v.get("uid")) for v in merged.walk("VEVENT")}
    assert uids == {"a", "b"}


def test_fetch_busy_calendar_decodes_bytes_event_data():
    block = _ics_vevent("c", datetime(2026, 8, 24, 9, 0, tzinfo=timezone.utc), datetime(2026, 8, 24, 9, 30, tzinfo=timezone.utc))
    calendar = FakeCalendar(event_blocks=[block.encode("utf-8")])

    merged = fetch_busy_calendar(calendar)

    uids = {str(v.get("uid")) for v in merged.walk("VEVENT")}
    assert uids == {"c"}


def test_fetch_busy_calendar_with_no_events_returns_empty_calendar():
    merged = fetch_busy_calendar(FakeCalendar(event_blocks=[]))
    assert list(merged.walk("VEVENT")) == []


def test_create_event_returns_uid_and_passes_core_fields():
    calendar = FakeCalendar()
    start = datetime(2026, 8, 24, 12, 0, tzinfo=MSK)
    end = datetime(2026, 8, 24, 12, 30, tzinfo=MSK)

    uid = create_event(calendar, summary="ivan_test & Альбато Партнерская программа", start=start, end=end)

    assert uid == "generated-uid"
    assert calendar.saved_kwargs["dtstart"] == start
    assert calendar.saved_kwargs["dtend"] == end
    assert calendar.saved_kwargs["summary"] == "ivan_test & Альбато Партнерская программа"


def test_create_event_includes_location_and_description_when_given():
    calendar = FakeCalendar()
    start = datetime(2026, 8, 24, 12, 0, tzinfo=MSK)
    end = datetime(2026, 8, 24, 12, 30, tzinfo=MSK)

    create_event(
        calendar,
        summary="ivan_test & Альбато Партнерская программа",
        start=start,
        end=end,
        location="https://telemost.360.yandex.ru/j/7926673398",
        description="Партнёрская программа Альбато",
    )

    assert calendar.saved_kwargs["location"] == "https://telemost.360.yandex.ru/j/7926673398"
    assert calendar.saved_kwargs["description"] == "Партнёрская программа Альбато"


def test_create_event_omits_empty_location_and_description():
    calendar = FakeCalendar()
    start = datetime(2026, 8, 24, 12, 0, tzinfo=MSK)
    end = datetime(2026, 8, 24, 12, 30, tzinfo=MSK)

    create_event(calendar, summary="ivan_test & Альбато Партнерская программа", start=start, end=end)

    assert "location" not in calendar.saved_kwargs
    assert "description" not in calendar.saved_kwargs
