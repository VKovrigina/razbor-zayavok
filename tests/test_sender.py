import asyncio

import pytest
from telethon.errors import (
    FloodWaitError,
    PeerFloodError,
    UsernameNotOccupiedError,
    UserPrivacyRestrictedError,
)

from telegram_channel import sender
from telegram_channel.sender import TelegramSendError, _send


class _FakeEntity:
    id = 12345


class _FakeClient:
    def __init__(
        self,
        get_entity_error=None,
        send_message_error=None,
        get_entity_hangs=False,
        send_message_hangs=False,
    ):
        self.get_entity_error = get_entity_error
        self.send_message_error = send_message_error
        self.get_entity_hangs = get_entity_hangs
        self.send_message_hangs = send_message_hangs
        self.sent = []

    async def get_entity(self, target):
        if self.get_entity_hangs:
            await asyncio.sleep(3600)  # имитирует "зомби"-соединение, которое никогда не отвечает
        if self.get_entity_error:
            raise self.get_entity_error
        return _FakeEntity()

    async def send_message(self, entity, text):
        if self.send_message_hangs:
            await asyncio.sleep(3600)
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


def test_send_raises_on_get_entity_hang_instead_of_blocking_forever(monkeypatch, recorded):
    monkeypatch.setattr(sender, "_TELETHON_CALL_TIMEOUT_SECONDS", 0.05)
    client = _FakeClient(get_entity_hangs=True)
    monkeypatch.setattr(sender, "get_client", lambda: client)

    with pytest.raises(TelegramSendError):
        asyncio.run(_send("target", "text"))

    assert recorded == []


def test_send_raises_on_send_message_hang_instead_of_blocking_forever(monkeypatch, recorded):
    monkeypatch.setattr(sender, "_TELETHON_CALL_TIMEOUT_SECONDS", 0.05)
    client = _FakeClient(send_message_hangs=True)
    monkeypatch.setattr(sender, "get_client", lambda: client)

    with pytest.raises(TelegramSendError):
        asyncio.run(_send("target", "text"))

    assert recorded == []


class _CacheMissClient(_FakeClient):
    """По числовому id пользователя нет в кэше сессии (сделки 40125553, 40179275), по username —
    находится."""

    def __init__(self):
        super().__init__()
        self.targets = []
        self.saved = 0
        self.session = self

    def save(self):
        self.saved += 1

    async def get_entity(self, target):
        self.targets.append(target)
        if isinstance(target, int):
            raise ValueError(f"Could not find the input entity for PeerUser(user_id={target})")
        return _FakeEntity()


@pytest.fixture()
def no_jitter(monkeypatch):
    async def _no_wait(low, high):
        return None

    monkeypatch.setattr(sender, "_jitter", _no_wait)


def test_send_reply_falls_back_to_username_when_peer_not_cached(monkeypatch, recorded, no_jitter):
    client = _CacheMissClient()
    monkeypatch.setattr(sender, "get_client", lambda: client)

    asyncio.run(sender.send_reply(6355684250, "Здравствуйте, ваша заявка актуальна?", "toronagasama"))

    assert client.targets == [6355684250, "toronagasama"]
    assert len(client.sent) == 1


def test_send_reply_without_username_still_raises(monkeypatch, recorded, no_jitter):
    monkeypatch.setattr(sender, "get_client", lambda: _CacheMissClient())

    with pytest.raises(TelegramSendError):
        asyncio.run(sender.send_reply(6355684250, "текст", None))


def test_send_reply_uses_peer_id_when_cached(monkeypatch, recorded, no_jitter):
    client = _FakeClient()
    targets = []
    original = client.get_entity

    async def tracking(target):
        targets.append(target)
        return await original(target)

    client.get_entity = tracking
    monkeypatch.setattr(sender, "get_client", lambda: client)

    asyncio.run(sender.send_reply(111, "текст", "someone"))

    assert targets == [111]


def test_send_reply_other_errors_not_retried_by_username(monkeypatch, recorded, no_jitter):
    client = _FakeClient(send_message_error=FloodWaitError(request=None, capture=30))
    targets = []
    original = client.get_entity

    async def tracking(target):
        targets.append(target)
        return await original(target)

    client.get_entity = tracking
    monkeypatch.setattr(sender, "get_client", lambda: client)

    with pytest.raises(TelegramSendError):
        asyncio.run(sender.send_reply(111, "текст", "someone"))
    assert targets == [111]


def test_send_first_contact_saves_session_cache_immediately(monkeypatch, recorded, no_jitter):
    client = _CacheMissClient()
    monkeypatch.setattr(sender, "get_client", lambda: client)

    asyncio.run(sender.send_first_contact("toronagasama", "Первое сообщение"))

    assert client.saved == 1


def test_send_first_contact_session_save_failure_does_not_fail_send(monkeypatch, recorded, no_jitter):
    client = _CacheMissClient()

    def broken_save():
        raise RuntimeError("database is locked")

    client.save = broken_save
    monkeypatch.setattr(sender, "get_client", lambda: client)

    assert asyncio.run(sender.send_first_contact("toronagasama", "Первое сообщение")) == 12345


def test_resolve_peer_id_by_username_and_saves_cache(monkeypatch):
    client = _CacheMissClient()
    monkeypatch.setattr(sender, "get_client", lambda: client)
    assert asyncio.run(sender.resolve_peer_id("toronagasama")) == 12345
    assert client.targets == ["toronagasama"] and client.saved == 1


def test_resolve_peer_id_unknown_username_raises(monkeypatch):
    monkeypatch.setattr(sender, "get_client", lambda: _FakeClient(get_entity_error=ValueError("no user")))
    with pytest.raises(TelegramSendError):
        asyncio.run(sender.resolve_peer_id("nobody"))
