from __future__ import annotations

import asyncio

import pytest
from telethon.errors import (
    FloodWaitError,
    PeerFloodError,
    UsernameNotOccupiedError,
    UserPrivacyRestrictedError,
)

from calls import telegram_sender as sender
from calls.telegram_sender import TelegramSendError, _send


class _FakeEntity:
    id = 12345


class _FakeClient:
    def __init__(self, get_entity_error=None, send_message_error=None):
        self.get_entity_error = get_entity_error
        self.send_message_error = send_message_error
        self.sent = []

    async def get_entity(self, target):
        if self.get_entity_error:
            raise self.get_entity_error
        return _FakeEntity()

    async def send_message(self, entity, text):
        if self.send_message_error:
            raise self.send_message_error
        self.sent.append((entity, text))


@pytest.fixture()
def recorded(monkeypatch):
    monkeypatch.setattr(sender.ratelimit, "is_send_allowed", lambda: True)
    monkeypatch.setattr(sender.ratelimit, "set_cooldown", lambda seconds: None)
    calls = []
    monkeypatch.setattr(sender.ratelimit, "record_send_attempt", lambda: calls.append(1))
    return calls


def test_send_records_attempt_on_success(monkeypatch, recorded):
    client = _FakeClient()
    monkeypatch.setattr(sender, "get_client", lambda: client)

    peer_id = asyncio.run(_send("target", "text"))

    assert peer_id == 12345
    assert recorded == [1]


def test_send_does_not_record_on_invalid_username(monkeypatch, recorded):
    client = _FakeClient(get_entity_error=UsernameNotOccupiedError(request=None))
    monkeypatch.setattr(sender, "get_client", lambda: client)

    with pytest.raises(TelegramSendError):
        asyncio.run(_send("target", "text"))

    assert recorded == []


def test_send_does_not_record_on_privacy_restricted(monkeypatch, recorded):
    """Ровно кейс "нет тг/приватность" из Decisions Log — вызывающий код должен поставить
    фолбэк-задачу, не тратя дневной лимит на несостоявшуюся доставку."""
    client = _FakeClient(send_message_error=UserPrivacyRestrictedError(request=None))
    monkeypatch.setattr(sender, "get_client", lambda: client)

    with pytest.raises(TelegramSendError):
        asyncio.run(_send("target", "text"))

    assert recorded == []


def test_send_records_attempt_on_flood_wait(monkeypatch, recorded):
    client = _FakeClient(send_message_error=FloodWaitError(request=None, capture=5))
    monkeypatch.setattr(sender, "get_client", lambda: client)

    with pytest.raises(TelegramSendError):
        asyncio.run(_send("target", "text"))

    assert recorded == [1]


def test_send_records_attempt_on_peer_flood(monkeypatch, recorded):
    client = _FakeClient(send_message_error=PeerFloodError(request=None))
    monkeypatch.setattr(sender, "get_client", lambda: client)

    with pytest.raises(TelegramSendError):
        asyncio.run(_send("target", "text"))

    assert recorded == [1]


def test_send_blocked_by_daily_cap_before_any_attempt(monkeypatch, recorded):
    monkeypatch.setattr(sender.ratelimit, "is_send_allowed", lambda: False)
    client = _FakeClient()
    monkeypatch.setattr(sender, "get_client", lambda: client)

    with pytest.raises(TelegramSendError):
        asyncio.run(_send("target", "text"))

    assert recorded == []
    assert client.sent == []
