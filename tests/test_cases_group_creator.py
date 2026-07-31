import asyncio

from cases import group_creator


class FakeChat:
    def __init__(self, chat_id):
        self.id = chat_id


class FakeUpdates:
    def __init__(self, chat_id):
        self.chats = [FakeChat(chat_id)]


class FakeCreateChatResult:
    """Мимикрирует messages.InvitedUsers (telethon >= 1.4x) — сам чат в .updates.chats,
    не в .chats напрямую (найдено на реальном e2e-прогоне 2026-07-31)."""

    def __init__(self, chat_id):
        self.updates = FakeUpdates(chat_id)


class FakeInvite:
    def __init__(self, link):
        self.link = link


class FakeClient:
    def __init__(self):
        self.calls = []

    async def get_participants(self, group_id):
        self.calls.append(("get_participants", group_id))

    async def get_input_entity(self, user_id):
        self.calls.append(("get_input_entity", user_id))
        return f"entity:{user_id}"

    async def get_entity(self, target):
        self.calls.append(("get_entity", target))
        return f"entity:{target}"

    async def send_message(self, entity, text):
        self.calls.append(("send_message", entity, text))

    async def __call__(self, request):
        self.calls.append(("request", request))
        if request.__class__.__name__ == "CreateChatRequest":
            return FakeCreateChatResult(chat_id=42)
        return FakeInvite(link="https://t.me/+invitehash")


def test_create_group_with_invite_calls_get_participants_before_create_chat(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(group_creator, "get_client", lambda: fake)

    asyncio.run(group_creator.create_group_with_invite(555, "Тест & Альбато"))

    names = [c[0] for c in fake.calls]
    assert names.index("get_participants") < names.index("request")


def test_create_group_with_invite_calls_get_participants_on_every_invocation(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(group_creator, "get_client", lambda: fake)

    asyncio.run(group_creator.create_group_with_invite(555, "Тест & Альбато"))
    asyncio.run(group_creator.create_group_with_invite(555, "Тест & Альбато"))

    assert [c[0] for c in fake.calls].count("get_participants") == 2


def test_create_group_with_invite_passes_title_to_create_chat_request(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(group_creator, "get_client", lambda: fake)

    asyncio.run(group_creator.create_group_with_invite(555, "@vr_kvr & Альбато"))

    create_chat_requests = [c[1] for c in fake.calls if c[0] == "request" and c[1].__class__.__name__ == "CreateChatRequest"]
    assert create_chat_requests[0].title == "@vr_kvr & Альбато"


def test_create_group_with_invite_returns_invite_link(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(group_creator, "get_client", lambda: fake)

    link = asyncio.run(group_creator.create_group_with_invite(555, "Тест & Альбато"))

    assert link == "https://t.me/+invitehash"


def test_create_group_with_invite_raises_when_entity_not_found(monkeypatch):
    class FailingClient(FakeClient):
        async def get_input_entity(self, user_id):
            raise ValueError("Could not find the input entity")

    monkeypatch.setattr(group_creator, "get_client", lambda: FailingClient())

    try:
        asyncio.run(group_creator.create_group_with_invite(555, "Тест & Альбато"))
        assert False, "expected ValueError to propagate"
    except ValueError:
        pass


def test_send_dm_calls_client_send_message(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(group_creator, "get_client", lambda: fake)

    asyncio.run(group_creator.send_dm("client_username", "текст сообщения"))

    assert ("get_entity", "client_username") in fake.calls
    assert ("send_message", "entity:client_username", "текст сообщения") in fake.calls
