from datetime import datetime
from zoneinfo import ZoneInfo

from calls.models import CallStatus

MSK = ZoneInfo("Europe/Moscow")


def slot(hour: int) -> datetime:
    return datetime(2026, 8, 24, hour, 0, tzinfo=MSK)


def test_get_call_none_when_absent(calls_repo):
    assert calls_repo.get_call(1) is None


def test_insert_offered_creates_row(calls_repo):
    assert calls_repo.insert_offered(1, 100, "Иван Иванов", "ivan_test", slot(12), slot(13)) is True
    call = calls_repo.get_call(1)
    assert call is not None
    assert call.status == CallStatus.OFFERED
    assert call.offered_slot_1 == slot(12)
    assert call.offered_slot_2 == slot(13)
    assert call.contact_name == "Иван Иванов"


def test_insert_offered_stores_telegram_peer_id_when_given(calls_repo):
    calls_repo.insert_offered(1, 100, "Иван", "ivan_test", slot(12), slot(13), telegram_peer_id=555)
    assert calls_repo.get_call(1).telegram_peer_id == 555


def test_insert_offered_returns_false_on_duplicate_lead_id(calls_repo):
    assert calls_repo.insert_offered(1, 100, "Иван", "ivan_test", slot(12), slot(13)) is True
    assert calls_repo.insert_offered(1, 200, "Другой", "other", slot(14), slot(15)) is False
    call = calls_repo.get_call(1)
    assert call.contact_id == 100


def test_list_reserved_slots_includes_offered_pair(calls_repo):
    calls_repo.insert_offered(1, 100, "Иван", "ivan_test", slot(12), slot(13))
    assert calls_repo.list_reserved_slots() == {slot(12), slot(13)}


def test_confirm_slot_transitions_to_confirmed(calls_repo):
    calls_repo.insert_offered(1, 100, "Иван", "ivan_test", slot(12), slot(13))
    assert calls_repo.confirm_slot(1, slot(12), "uid-1") is True
    call = calls_repo.get_call(1)
    assert call.status == CallStatus.CONFIRMED
    assert call.confirmed_slot == slot(12)
    assert call.calendar_event_uid == "uid-1"


def test_confirm_slot_fails_for_unknown_lead(calls_repo):
    assert calls_repo.confirm_slot(999, slot(12), "uid-1") is False


def test_list_reserved_slots_releases_unchosen_slot_after_confirm(calls_repo):
    calls_repo.insert_offered(1, 100, "Иван", "ivan_test", slot(12), slot(13))
    calls_repo.confirm_slot(1, slot(12), "uid-1")
    assert calls_repo.list_reserved_slots() == {slot(12)}


def test_reoffer_slots_replaces_pair_and_stays_offered(calls_repo):
    calls_repo.insert_offered(1, 100, "Иван", "ivan_test", slot(12), slot(13))
    assert calls_repo.reoffer_slots(1, slot(14), slot(14)) is True
    call = calls_repo.get_call(1)
    assert call.status == CallStatus.OFFERED
    assert call.offered_slot_1 == slot(14)
    assert calls_repo.list_reserved_slots() == {slot(14)}


def test_insert_no_telegram_creates_row_without_slots(calls_repo):
    assert calls_repo.insert_no_telegram(1, 100, "Иван") is True
    call = calls_repo.get_call(1)
    assert call.status == CallStatus.NO_TELEGRAM
    assert call.offered_slot_1 is None


def test_kv_roundtrip(calls_repo):
    calls_repo.set_kv("last_template", "1")
    assert calls_repo.get_kv("last_template") == "1"
    assert calls_repo.get_kv("missing") is None


def test_daily_cap_increments_and_reports(calls_repo):
    assert calls_repo.get_daily_send_count() == 0
    assert calls_repo.increment_and_check_daily_cap(cap=2) is True
    assert calls_repo.increment_and_check_daily_cap(cap=2) is True
    assert calls_repo.increment_and_check_daily_cap(cap=2) is False
    assert calls_repo.get_daily_send_count() == 3
