import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from db.models import Channel, Status
from telegram_channel import catch_up, listener

NOW = datetime(2026, 11, 6, 13, 30, tzinfo=timezone.utc)
PEER = 576316304


def _msg(minutes_ago, text, out=False):
    return SimpleNamespace(date=NOW - timedelta(minutes=minutes_ago), raw_text=text, out=out)


def _dialog(messages, peer_id=PEER, is_user=True, bot=False):
    """messages — от новых к старым, как отдаёт telethon."""
    entity = SimpleNamespace(id=peer_id, bot=bot)
    return SimpleNamespace(is_user=is_user, entity=entity, message=messages[0], _history=messages)


class FakeClient:
    def __init__(self, dialogs):
        self.dialogs = dialogs

    async def get_dialogs(self, limit):
        return self.dialogs

    async def get_messages(self, entity, limit):
        for d in self.dialogs:
            if d.entity is entity:
                return d._history[:limit]
        raise ValueError("unknown entity")


@pytest.fixture()
def handled(monkeypatch):
    calls = []

    async def fake_handle(deal_id, text, channel):
        calls.append((deal_id, text, channel))

    monkeypatch.setattr("core.state_machine.handle_incoming_reply", fake_handle)
    return calls


def _awaiting_deal(repo, deal_id=1, peer_id=PEER, sent_minutes_ago=60):
    repo.create_deal_new(deal_id, 100, "Эльвина", "emarsovna", None, "сдэк", "Кейс")
    repo.set_telegram_peer_id(deal_id, peer_id)
    repo.set_awaiting_first_sent(deal_id, "telegram", peer_id, "2026-11-09T11:00:00+00:00")
    repo.log_event(deal_id, "out", "telegram", "Здравствуйте, ваша заявка актуальна?")
    sent_at = (NOW - timedelta(minutes=sent_minutes_ago)).isoformat()
    with repo._connect() as conn:
        conn.execute("UPDATE events_log SET ts = ? WHERE deal_id = ?", (sent_at, deal_id))


def _run(client, monkeypatch):
    monkeypatch.setattr(catch_up, "get_client", lambda: client)
    asyncio.run(catch_up.catch_up_once(now=NOW))


def test_get_last_event_ts_none_without_events(repo):
    repo.create_deal_new(1, 100, "Иван", "ivan", None, "s", "c")
    assert repo.get_last_event_ts(1) is None


def test_get_last_event_ts_returns_latest(repo):
    repo.create_deal_new(1, 100, "Иван", "ivan", None, "s", "c")
    repo.log_event(1, "out", "telegram", "раз")
    repo.log_event(1, "in", "telegram", "два")
    with repo._connect() as conn:
        latest = conn.execute("SELECT max(ts) FROM events_log WHERE deal_id = 1").fetchone()[0]
    assert repo.get_last_event_ts(1) == latest


def test_missed_reply_is_processed(repo, handled, monkeypatch):
    _awaiting_deal(repo)
    history = [_msg(5, "подскажите условия цены"), _msg(6, "Добрый день"),
               _msg(60.5, "Здравствуйте, ваша заявка актуальна?", out=True), _msg(90, "старое")]
    _run(FakeClient([_dialog(history)]), monkeypatch)
    assert handled == [(1, "Добрый день\nподскажите условия цены", Channel.TELEGRAM)]


def test_last_message_ours_is_skipped(repo, handled, monkeypatch):
    _awaiting_deal(repo)
    history = [_msg(5, "ответ Варвары вручную", out=True), _msg(6, "вопрос клиента")]
    _run(FakeClient([_dialog(history)]), monkeypatch)
    assert handled == []


def test_fresh_message_left_to_live_handler(repo, handled, monkeypatch):
    _awaiting_deal(repo)
    _run(FakeClient([_dialog([_msg(1, "только что")])]), monkeypatch)
    assert handled == []


def test_already_processed_message_is_skipped(repo, handled, monkeypatch):
    _awaiting_deal(repo, sent_minutes_ago=3)
    _run(FakeClient([_dialog([_msg(10, "уже обработано")])]), monkeypatch)
    assert handled == []


def test_escalated_deal_is_skipped(repo, handled, monkeypatch):
    _awaiting_deal(repo)
    repo.escalate(1, Status.ESCALATED_POSITIVE)
    _run(FakeClient([_dialog([_msg(5, "вопрос")])]), monkeypatch)
    assert handled == []


@pytest.mark.parametrize("dialog_kwargs", [
    {"peer_id": 999},          # не наш клиент
    {"bot": True},
    {"is_user": False},        # группа/канал
])
def test_foreign_dialogs_are_skipped(repo, handled, monkeypatch, dialog_kwargs):
    _awaiting_deal(repo)
    _run(FakeClient([_dialog([_msg(5, "привет")], **dialog_kwargs)]), monkeypatch)
    assert handled == []


def test_peer_in_aggregation_window_is_skipped(repo, handled, monkeypatch):
    _awaiting_deal(repo)
    monkeypatch.setitem(listener._pending, PEER, ["в процессе"])
    _run(FakeClient([_dialog([_msg(5, "вопрос")])]), monkeypatch)
    assert handled == []


def test_error_in_one_dialog_does_not_stop_others(repo, handled, monkeypatch):
    _awaiting_deal(repo, deal_id=1, peer_id=PEER)
    _awaiting_deal(repo, deal_id=2, peer_id=777)
    broken = _dialog([_msg(5, "сломается")], peer_id=PEER)
    broken._history = None  # get_messages упадёт
    ok = _dialog([_msg(5, "вопрос")], peer_id=777)
    _run(FakeClient([broken, ok]), monkeypatch)
    assert handled == [(2, "вопрос", Channel.TELEGRAM)]


def test_too_old_message_is_skipped(repo, handled, monkeypatch):
    _awaiting_deal(repo, sent_minutes_ago=4 * 24 * 60)
    _run(FakeClient([_dialog([_msg(3 * 24 * 60, "ответ трёхдневной давности")])]), monkeypatch)
    assert handled == []
