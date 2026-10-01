from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from calls import booking
from calls.models import CallStatus
from calls.telegram_sender import TelegramSendError

MSK = ZoneInfo("Europe/Moscow")


def msk(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=MSK)


class FakeCalendar:
    def __init__(self, busy_starts=None):
        self.busy_starts = busy_starts or set()
        self.created = None

    def save_event(self, **kwargs):
        self.created = kwargs

        class _Event:
            icalendar_component = {"uid": "event-uid-1"}

        return _Event()


def _lead(lead_id=1, contact_id=100):
    return {"id": lead_id, "_embedded": {"contacts": [{"id": contact_id}]}}


def _patch_common(monkeypatch, calls_repo, telegram_username="ivan_test", calendar=None):
    monkeypatch.setattr(booking, "repository", calls_repo)
    calendar = calendar or FakeCalendar()
    monkeypatch.setattr(booking.calendar_client, "get_calendar", lambda: calendar)
    # fetch_busy_calendar пропускается "как есть" (identity) — is_slot_free ниже читает
    # busy_starts прямо с FakeCalendar, реальный recurring_ical_events не участвует в тесте.
    monkeypatch.setattr(booking.calendar_client, "fetch_busy_calendar", lambda cal: cal)
    monkeypatch.setattr(
        booking.calendar_client, "is_slot_free", lambda busy_cal, start, end: start not in busy_cal.busy_starts
    )
    monkeypatch.setattr(
        booking.amo_client, "get_contact", lambda contact_id: {"name": "Иван Иванов"}
    )
    monkeypatch.setattr(
        booking.contact_utils,
        "extract_telegram_username",
        lambda contact, field_id: telegram_username,
    )
    monkeypatch.setattr(booking, "settings", _fake_settings())

    fallback_calls = []
    monkeypatch.setattr(booking.amo_actions, "create_fallback_task", lambda lead_id: fallback_calls.append(lead_id))
    written_calls = []
    monkeypatch.setattr(booking.amo_actions, "move_to_written_in_tg", lambda lead_id: written_calls.append(lead_id))
    meeting_calls = []
    monkeypatch.setattr(booking.amo_actions, "move_to_meeting", lambda lead_id: meeting_calls.append(lead_id))
    meeting_tasks = []
    monkeypatch.setattr(
        booking.amo_actions, "create_meeting_task", lambda lead_id, at: meeting_tasks.append((lead_id, at))
    )

    sent = []

    async def fake_send_first_contact(username, text):
        sent.append(("first", username, text))
        return 555

    async def fake_send_reply(peer_id, text):
        sent.append(("reply", peer_id, text))

    monkeypatch.setattr(booking.telegram_sender, "send_first_contact", fake_send_first_contact)
    monkeypatch.setattr(booking.telegram_sender, "send_reply", fake_send_reply)

    return {
        "calendar": calendar,
        "fallback_calls": fallback_calls,
        "written_calls": written_calls,
        "meeting_calls": meeting_calls,
        "meeting_tasks": meeting_tasks,
        "sent": sent,
    }


class _FakeSettings:
    amocrm_calls_contact_field_id_telegram = 949077
    calendar_telemost_link = "https://telemost.360.yandex.ru/j/7926673398"


def _fake_settings():
    return _FakeSettings()


def test_offer_skips_already_processed_lead(calls_repo, monkeypatch):
    recorded = _patch_common(monkeypatch, calls_repo)
    calls_repo.insert_no_telegram(1, 100, "Иван")

    result = asyncio.run(booking.offer_slots_for_lead(_lead(), now=msk(24, 9, 0)))

    assert result == "already_processed"
    assert recorded["sent"] == []
    assert recorded["fallback_calls"] == []


def test_offer_creates_fallback_task_when_no_telegram(calls_repo, monkeypatch):
    recorded = _patch_common(monkeypatch, calls_repo, telegram_username=None)

    result = asyncio.run(booking.offer_slots_for_lead(_lead(), now=msk(24, 9, 0)))

    assert result == "no_telegram"
    assert recorded["fallback_calls"] == [1]
    call = calls_repo.get_call(1)
    assert call.status == CallStatus.NO_TELEGRAM


def test_offer_happy_path_sends_and_records_offer(calls_repo, monkeypatch):
    recorded = _patch_common(monkeypatch, calls_repo)

    result = asyncio.run(booking.offer_slots_for_lead(_lead(), now=msk(24, 9, 0)))

    assert result == "offered"
    assert recorded["written_calls"] == [1]
    kind, username, text = recorded["sent"][0]
    assert kind == "first"
    assert username == "ivan_test"
    assert "12:00" in text and "12:30" in text
    call = calls_repo.get_call(1)
    assert call.status == CallStatus.OFFERED
    assert call.telegram_peer_id == 555
    assert call.offered_slot_1 == msk(24, 12, 0)


def test_offer_falls_back_when_telegram_send_fails(calls_repo, monkeypatch):
    recorded = _patch_common(monkeypatch, calls_repo)

    async def failing_send(username, text):
        raise TelegramSendError("UserPrivacyRestricted")

    monkeypatch.setattr(booking.telegram_sender, "send_first_contact", failing_send)

    result = asyncio.run(booking.offer_slots_for_lead(_lead(), now=msk(24, 9, 0)))

    assert result == "no_telegram"
    assert recorded["fallback_calls"] == [1]
    assert calls_repo.get_call(1).status == CallStatus.NO_TELEGRAM


def test_offer_alerts_when_no_slots_available(calls_repo, monkeypatch):
    all_day_slots = {msk(24, h, m) for h, m in [(12, 0), (12, 30), (13, 0), (13, 30), (14, 0), (14, 30)]}
    recorded = _patch_common(monkeypatch, calls_repo, calendar=FakeCalendar(busy_starts=all_day_slots))
    monkeypatch.setattr(booking, "SEARCH_DAYS_LIMIT", 1)

    result = asyncio.run(booking.offer_slots_for_lead(_lead(), now=msk(24, 9, 0)))

    assert result == "no_slots"


def test_confirm_meeting_creates_event_task_and_summary(calls_repo, monkeypatch):
    recorded = _patch_common(monkeypatch, calls_repo)
    calls_repo.insert_offered(1, 100, "Иван Иванов", "ivan_test", msk(24, 12, 0), msk(24, 12, 30), telegram_peer_id=555)

    asyncio.run(booking.confirm_meeting(1, msk(24, 12, 0)))

    calendar = recorded["calendar"]
    assert calendar.created["dtstart"] == msk(24, 12, 0)
    assert calendar.created["location"] == "https://telemost.360.yandex.ru/j/7926673398"
    assert "ivan_test" in calendar.created["summary"]

    call = calls_repo.get_call(1)
    assert call.status == CallStatus.CONFIRMED
    assert call.calendar_event_uid == "event-uid-1"

    assert recorded["meeting_calls"] == [1]
    assert recorded["meeting_tasks"] == [(1, msk(24, 12, 0))]

    kind, peer_id, text = recorded["sent"][0]
    assert kind == "reply"
    assert peer_id == 555
    assert "12:00" in text
    assert "24 августа" in text
    assert "telemost" in text.lower()


def test_decline_and_reoffer_sends_new_pair(calls_repo, monkeypatch):
    recorded = _patch_common(monkeypatch, calls_repo)
    calls_repo.insert_offered(1, 100, "Иван Иванов", "ivan_test", msk(24, 12, 0), msk(24, 12, 30), telegram_peer_id=555)

    result = asyncio.run(booking.decline_and_reoffer(1, now=msk(24, 9, 0)))

    assert result == (msk(24, 13, 0), msk(24, 13, 30))
    call = calls_repo.get_call(1)
    assert call.offered_slot_1 == msk(24, 13, 0)
    kind, peer_id, text = recorded["sent"][0]
    assert "13:00" in text and "13:30" in text


def test_decline_and_reoffer_returns_none_when_no_slots_left(calls_repo, monkeypatch):
    all_day_slots = {msk(24, h, m) for h, m in [(12, 0), (12, 30), (13, 0), (13, 30), (14, 0), (14, 30)]}
    recorded = _patch_common(monkeypatch, calls_repo, calendar=FakeCalendar(busy_starts=all_day_slots))
    monkeypatch.setattr(booking, "SEARCH_DAYS_LIMIT", 1)
    calls_repo.insert_offered(1, 100, "Иван Иванов", "ivan_test", msk(24, 12, 0), msk(24, 12, 30), telegram_peer_id=555)

    result = asyncio.run(booking.decline_and_reoffer(1, now=msk(24, 9, 0)))

    assert result is None
    assert recorded["sent"] == []
