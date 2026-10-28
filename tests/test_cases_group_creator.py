from __future__ import annotations

import asyncio

import pytest

from cases import group_creator


from telethon.errors import ChatNotModifiedError
from telethon.tl.types import DialogFilter, InputPeerUser, TextWithEntities

INTRO = "Чат для обсуждения\n\nТекст ТЗ"


class FakeChannel:
    def __init__(self, channel_id, access_hash):
        self.id = channel_id
        self.access_hash = access_hash


class FakeCreateChannelResult:
    def __init__(self):
        self.chats = [FakeChannel(42, 777)]


class FakeInvite:
    def __init__(self, link):
        self.link = link


def _settings_folder(include_count=2, folder_id=228, title="Настройки"):
    return DialogFilter(
        id=folder_id,
        title=TextWithEntities(text=title, entities=[]),
        pinned_peers=[],
        include_peers=[InputPeerUser(user_id=i, access_hash=i) for i in range(include_count)],
        exclude_peers=[],
    )


class FakeFilters:
    def __init__(self, filters):
        self.filters = filters


class FakeClient:
    def __init__(self, hangs: set[str] | None = None, fails: dict | None = None, folders=None):
        self.calls = []
        self.hangs = hangs or set()
        self.fails = fails or {}
        self.folders = [_settings_folder()] if folders is None else folders

    async def get_participants(self, group_id):
        if "get_participants" in self.hangs:
            await asyncio.sleep(3600)
        self.calls.append(("get_participants", group_id))

    async def get_input_entity(self, user_id):
        if "get_input_entity" in self.hangs:
            await asyncio.sleep(3600)
        self.calls.append(("get_input_entity", user_id))
        return f"entity:{user_id}"

    async def get_entity(self, target):
        if "get_entity" in self.hangs:
            await asyncio.sleep(3600)
        self.calls.append(("get_entity", target))
        return f"entity:{target}"

    async def send_message(self, entity, text):
        if "send_message" in self.hangs:
            await asyncio.sleep(3600)
        if "send_message" in self.fails:
            raise self.fails["send_message"]
        self.calls.append(("send_message", entity, text))

    async def __call__(self, request):
        name = request.__class__.__name__
        if "request" in self.hangs:
            await asyncio.sleep(3600)
        if name in self.fails:
            raise self.fails[name]
        self.calls.append(("request", request))
        if name == "CreateChannelRequest":
            return FakeCreateChannelResult()
        if name == "GetDialogFiltersRequest":
            return FakeFilters(self.folders)
        if name == "ExportChatInviteRequest":
            return FakeInvite(link="https://t.me/+invitehash")
        return True

    def requests(self, name):
        return [c[1] for c in self.calls if c[0] == "request" and c[1].__class__.__name__ == name]


def _create(fake, monkeypatch, title="Тест & Альбато"):
    monkeypatch.setattr(group_creator, "get_client", lambda: fake)
    return asyncio.run(group_creator.create_group_with_invite(555, title, INTRO))


def test_create_group_with_invite_calls_get_participants_before_create(monkeypatch):
    fake = FakeClient()
    _create(fake, monkeypatch)
    names = [c[0] for c in fake.calls]
    assert names.index("get_participants") < names.index("request")


def test_create_group_with_invite_calls_get_participants_on_every_invocation(monkeypatch):
    fake = FakeClient()
    _create(fake, monkeypatch)
    _create(fake, monkeypatch)
    assert [c[0] for c in fake.calls].count("get_participants") == 2


def test_creates_supergroup_with_title_and_invites_partner(monkeypatch):
    fake = FakeClient()
    _create(fake, monkeypatch, title="@vr_kvr & Альбато")
    create = fake.requests("CreateChannelRequest")[0]
    assert create.title == "@vr_kvr & Альбато"
    assert create.megagroup is True
    assert fake.requests("InviteToChannelRequest")[0].users == ["entity:555"]


def test_history_visible_for_new_members(monkeypatch):
    fake = FakeClient()
    _create(fake, monkeypatch)
    assert fake.requests("TogglePreHistoryHiddenRequest")[0].enabled is False


def test_intro_message_with_case_posted_in_chat(monkeypatch):
    fake = FakeClient()
    _create(fake, monkeypatch)
    sent = [c for c in fake.calls if c[0] == "send_message"]
    assert len(sent) == 1
    assert sent[0][1].channel_id == 42
    assert sent[0][2] == INTRO


def test_chat_muted_forever(monkeypatch):
    fake = FakeClient()
    _create(fake, monkeypatch)
    notify = fake.requests("UpdateNotifySettingsRequest")[0]
    assert notify.peer.peer.channel_id == 42
    assert notify.settings.mute_until >= 2**31 - 1


def test_chat_added_to_settings_folder_keeping_existing_chats(monkeypatch):
    fake = FakeClient()
    _create(fake, monkeypatch)
    update = fake.requests("UpdateDialogFilterRequest")[0]
    assert update.id == 228
    assert update.filter.title.text == "Настройки"
    assert len(update.filter.include_peers) == 3
    assert update.filter.include_peers[-1].channel_id == 42


def test_returns_link_and_no_warnings(monkeypatch):
    link, warnings = _create(FakeClient(), monkeypatch)
    assert link == "https://t.me/+invitehash"
    assert warnings == []


def test_missing_settings_folder_is_created(monkeypatch):
    fake = FakeClient(folders=[])
    link, warnings = _create(fake, monkeypatch)
    update = fake.requests("UpdateDialogFilterRequest")[0]
    assert warnings == []
    assert update.filter.title.text == "Настройки"
    assert update.id == 2  # первый свободный id папки
    assert [p.channel_id for p in update.filter.include_peers] == [42]


def test_full_settings_folder_creates_next_numbered_folder(monkeypatch):
    fake = FakeClient(folders=[_settings_folder(include_count=100)])
    link, warnings = _create(fake, monkeypatch)
    update = fake.requests("UpdateDialogFilterRequest")[0]
    assert warnings == []
    assert update.filter.title.text == "Настройки 2"
    assert update.id == 2
    assert [p.channel_id for p in update.filter.include_peers] == [42]
    assert not update.filter.contacts and not update.filter.groups  # только явно добавленные чаты


def test_full_settings_folder_uses_existing_numbered_folder_with_room(monkeypatch):
    fake = FakeClient(folders=[
        _settings_folder(include_count=100),
        _settings_folder(include_count=10, folder_id=2, title="Настройки 2"),
    ])
    _create(fake, monkeypatch)
    update = fake.requests("UpdateDialogFilterRequest")[0]
    assert update.id == 2
    assert len(update.filter.include_peers) == 11


def test_new_folder_id_skips_used_ids(monkeypatch):
    fake = FakeClient(folders=[
        _settings_folder(include_count=100, folder_id=2),
        _settings_folder(include_count=100, folder_id=3, title="Настройки 2"),
    ])
    _create(fake, monkeypatch)
    update = fake.requests("UpdateDialogFilterRequest")[0]
    assert update.filter.title.text == "Настройки 3"
    assert update.id == 4


def test_folder_update_error_is_warning_not_failure(monkeypatch):
    fake = FakeClient(fails={"UpdateDialogFilterRequest": RuntimeError("FILTER_INCLUDE_TOO_MUCH")})
    link, warnings = _create(fake, monkeypatch)
    assert link == "https://t.me/+invitehash"
    assert len(warnings) == 1 and "Настройки" in warnings[0]


def test_mute_error_is_warning_not_failure(monkeypatch):
    fake = FakeClient(fails={"UpdateNotifySettingsRequest": RuntimeError("boom")})
    link, warnings = _create(fake, monkeypatch)
    assert link == "https://t.me/+invitehash"
    assert len(warnings) == 1 and "уведомлен" in warnings[0]


def test_intro_message_error_is_warning_not_failure(monkeypatch):
    fake = FakeClient(fails={"send_message": RuntimeError("boom")})
    link, warnings = _create(fake, monkeypatch)
    assert link == "https://t.me/+invitehash"
    assert len(warnings) == 1 and "сообщени" in warnings[0]


def test_history_already_visible_is_not_warning(monkeypatch):
    fake = FakeClient(fails={"TogglePreHistoryHiddenRequest": ChatNotModifiedError(request=None)})
    link, warnings = _create(fake, monkeypatch)
    assert warnings == []


def test_history_toggle_error_is_warning(monkeypatch):
    fake = FakeClient(fails={"TogglePreHistoryHiddenRequest": RuntimeError("boom")})
    link, warnings = _create(fake, monkeypatch)
    assert link == "https://t.me/+invitehash"
    assert len(warnings) == 1 and "истори" in warnings[0]


def test_create_group_with_invite_raises_when_entity_not_found(monkeypatch):
    class FailingClient(FakeClient):
        async def get_input_entity(self, user_id):
            raise ValueError("Could not find the input entity")

    with pytest.raises(ValueError):
        _create(FailingClient(), monkeypatch)


def test_partner_invite_error_fails_creation(monkeypatch):
    fake = FakeClient(fails={"InviteToChannelRequest": RuntimeError("USER_PRIVACY_RESTRICTED")})
    with pytest.raises(RuntimeError):
        _create(fake, monkeypatch)


def test_send_dm_calls_client_send_message(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(group_creator, "get_client", lambda: fake)

    asyncio.run(group_creator.send_dm("client_username", "текст сообщения"))

    assert ("get_entity", "client_username") in fake.calls
    assert ("send_message", "entity:client_username", "текст сообщения") in fake.calls


def test_create_group_with_invite_raises_on_get_participants_hang(monkeypatch):
    monkeypatch.setattr(group_creator, "_TELETHON_CALL_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(asyncio.TimeoutError):
        _create(FakeClient(hangs={"get_participants"}), monkeypatch)


def test_create_group_with_invite_raises_on_create_request_hang(monkeypatch):
    monkeypatch.setattr(group_creator, "_TELETHON_CALL_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(asyncio.TimeoutError):
        _create(FakeClient(hangs={"request"}), monkeypatch)


def test_send_dm_raises_on_get_entity_hang(monkeypatch):
    monkeypatch.setattr(group_creator, "_TELETHON_CALL_TIMEOUT_SECONDS", 0.05)
    fake = FakeClient(hangs={"get_entity"})
    monkeypatch.setattr(group_creator, "get_client", lambda: fake)

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(group_creator.send_dm("client_username", "текст сообщения"))


def test_send_dm_raises_on_send_message_hang(monkeypatch):
    monkeypatch.setattr(group_creator, "_TELETHON_CALL_TIMEOUT_SECONDS", 0.05)
    fake = FakeClient(hangs={"send_message"})
    monkeypatch.setattr(group_creator, "get_client", lambda: fake)

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(group_creator.send_dm("client_username", "текст сообщения"))
