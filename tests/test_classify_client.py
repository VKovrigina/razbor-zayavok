import dataclasses
from types import SimpleNamespace

from classify import client as classify_client
from db.models import ReplyCategory


def _fake_anthropic(monkeypatch, category="positive"):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        block = SimpleNamespace(type="tool_use", name="classify_reply", input={"category": category})
        return SimpleNamespace(content=[block])

    test_settings = dataclasses.replace(classify_client.settings, anthropic_api_key="test-key")
    monkeypatch.setattr(classify_client, "settings", test_settings)
    monkeypatch.setattr(classify_client, "_client", SimpleNamespace(messages=SimpleNamespace(create=create)))
    return calls


def test_last_bot_message_passed_to_claude(monkeypatch):
    calls = _fake_anthropic(monkeypatch)

    result = classify_client.classify_sync("нет", "кейс", "Хотите что-то дополнить к задаче?")

    assert result == ReplyCategory.POSITIVE
    content = calls[0]["messages"][0]["content"]
    assert "Хотите что-то дополнить к задаче?" in content
    assert content.index("Хотите что-то дополнить") < content.index("Ответ клиента")


def test_without_last_bot_message_uses_dash(monkeypatch):
    calls = _fake_anthropic(monkeypatch, "negative")

    result = classify_client.classify_sync("нет", "кейс")

    assert result == ReplyCategory.NEGATIVE
    assert "Последнее сообщение бота клиенту:\n—" in calls[0]["messages"][0]["content"]


def test_not_relevant_category_supported(monkeypatch):
    _fake_anthropic(monkeypatch, "not_relevant")

    assert classify_client.classify_sync("нет, спасибо", "кейс", "Здравствуйте, ваша заявка актуальна?") == (
        ReplyCategory.NOT_RELEVANT
    )
    assert "not_relevant" in classify_client._TOOL["input_schema"]["properties"]["category"]["enum"]
