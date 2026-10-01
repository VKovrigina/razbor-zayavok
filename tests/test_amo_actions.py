from amo import actions as amo_actions
from amo.actions import clean_username
from amo.client import amo_client


def test_clean_username_accepts_plain_username():
    assert clean_username("ivan_test") == "ivan_test"


def test_clean_username_strips_at_prefix():
    assert clean_username("@ivan_test") == "ivan_test"


def test_clean_username_strips_telegram_url():
    assert clean_username("https://t.me/ivan_test") == "ivan_test"


def test_clean_username_rejects_placeholder_dash():
    """Найдено на проде 2026-07-24: поле Telegram в CRM не заполнено, вместо пустой строки
    приходит "-" — это не username, а два разных клиента с такой заглушкой не должны считаться
    одним и тем же человеком при проверке конфликта (см. BACKLOG.md)."""
    assert clean_username("-") is None


def test_clean_username_rejects_empty_and_none():
    assert clean_username("") is None
    assert clean_username(None) is None


def test_clean_username_rejects_too_short():
    assert clean_username("abcd") is None  # 4 символа — меньше минимума в 5


def test_clean_username_accepts_minimum_length():
    assert clean_username("abcde") == "abcde"


def test_clean_username_rejects_leading_digit():
    assert clean_username("12345") is None


def test_clean_username_rejects_placeholder_words():
    assert clean_username("нет") is None
    assert clean_username("не указан") is None


def test_set_channel_tag_telegram_maps_to_tg(monkeypatch):
    calls = []
    monkeypatch.setattr(amo_actions.amo_client, "add_lead_tag", lambda lead_id, tag: calls.append((lead_id, tag)))

    amo_actions.set_channel_tag(42, "telegram")

    assert calls == [(42, "ТГ")]


def test_set_channel_tag_email_maps_to_pochta(monkeypatch):
    calls = []
    monkeypatch.setattr(amo_actions.amo_client, "add_lead_tag", lambda lead_id, tag: calls.append((lead_id, tag)))

    amo_actions.set_channel_tag(42, "email")

    assert calls == [(42, "Почта")]


def test_add_lead_tag_adds_when_no_existing_tags(monkeypatch):
    monkeypatch.setattr(amo_client, "get_lead", lambda lead_id: {"_embedded": {"tags": []}})
    patch_calls = []
    monkeypatch.setattr(amo_client, "patch", lambda path, json: patch_calls.append((path, json)))

    amo_client.add_lead_tag(42, "ТГ")

    assert patch_calls == [("/api/v4/leads/42", {"_embedded": {"tags": [{"name": "ТГ"}]}})]


def test_add_lead_tag_preserves_existing_tags(monkeypatch):
    """PATCH .../tags заменяет весь список тегов сделки — нельзя потерять уже стоящие теги."""
    monkeypatch.setattr(
        amo_client,
        "get_lead",
        lambda lead_id: {"_embedded": {"tags": [{"id": 111, "name": "Срочно"}]}},
    )
    patch_calls = []
    monkeypatch.setattr(amo_client, "patch", lambda path, json: patch_calls.append((path, json)))

    amo_client.add_lead_tag(42, "ТГ")

    assert patch_calls == [
        ("/api/v4/leads/42", {"_embedded": {"tags": [{"id": 111}, {"name": "ТГ"}]}})
    ]


def test_add_lead_tag_is_idempotent_if_already_present(monkeypatch):
    monkeypatch.setattr(
        amo_client,
        "get_lead",
        lambda lead_id: {"_embedded": {"tags": [{"id": 222, "name": "ТГ"}]}},
    )
    patch_calls = []
    monkeypatch.setattr(amo_client, "patch", lambda path, json: patch_calls.append((path, json)))

    amo_client.add_lead_tag(42, "ТГ")

    assert patch_calls == []


def test_set_lead_custom_field_sends_field_id_and_value(monkeypatch):
    patch_calls = []
    monkeypatch.setattr(amo_client, "patch", lambda path, json: patch_calls.append((path, json)))

    amo_client.set_lead_custom_field(42, 976101, "🔸Сервисы: amoCRM\n🔸Задача: тест")

    assert patch_calls == [
        (
            "/api/v4/leads/42",
            {"custom_fields_values": [{"field_id": 976101, "values": [{"value": "🔸Сервисы: amoCRM\n🔸Задача: тест"}]}]},
        )
    ]


def test_set_full_spec_field_uses_configured_field_id(monkeypatch):
    import dataclasses

    from config import settings as base_settings

    monkeypatch.setattr(amo_actions, "settings", dataclasses.replace(base_settings, amocrm_field_id_full_spec=976101))
    calls = []
    monkeypatch.setattr(amo_actions.amo_client, "set_lead_custom_field", lambda lead_id, field_id, value: calls.append((lead_id, field_id, value)))

    amo_actions.set_full_spec_field(42, "текст ТЗ")

    assert calls == [(42, 976101, "текст ТЗ")]


def test_set_messaging_tariff_tag_uses_fixed_name(monkeypatch):
    calls = []
    monkeypatch.setattr(amo_actions.amo_client, "add_lead_tag", lambda lead_id, tag: calls.append((lead_id, tag)))

    amo_actions.set_messaging_tariff_tag(42)

    assert calls == [(42, "Месседжинг")]
