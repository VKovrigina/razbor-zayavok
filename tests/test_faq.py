import dataclasses

import pytest

from classify import faq
from config import settings as base_settings


def test_match_faq_sync_returns_none_without_api_key(monkeypatch):
    monkeypatch.setattr("classify.faq.FAQ_ENABLED", True)
    no_key_settings = dataclasses.replace(base_settings, anthropic_api_key="")
    monkeypatch.setattr("classify.faq.settings", no_key_settings)

    assert faq.match_faq_sync("сколько это стоит?", "CRM + Sheets") is None


def test_match_faq_sync_returns_none_when_disabled_even_with_api_key(monkeypatch):
    """Если бы FAQ_ENABLED был выключен (например, руками при инциденте) — совпадений быть не
    должно, даже с валидным ключом. Флаг сейчас включён (см. classify/faq.py) — тест на сам
    механизм отключения, а не на текущее значение флага."""
    monkeypatch.setattr("classify.faq.FAQ_ENABLED", False)
    key_settings = dataclasses.replace(base_settings, anthropic_api_key="sk-test-not-real")
    monkeypatch.setattr("classify.faq.settings", key_settings)

    assert faq.match_faq_sync("сколько это стоит?", "CRM + Sheets") is None


def test_get_answer_known_ids_return_text():
    for entry in faq.FAQ_ENTRIES:
        answer = faq.get_answer(entry["id"])
        assert isinstance(answer, str) and answer


def test_get_answer_unknown_id_raises_key_error():
    with pytest.raises(KeyError):
        faq.get_answer("faq_does_not_exist")


def test_placeholder_entries_excluded_from_usable_catalog():
    """Черновики с "[ЗАПОЛНИТЬ" не должны быть доступны для подбора — иначе бот отправит
    заглушку живому клиенту."""
    usable_ids = {e["id"] for e in faq._USABLE_ENTRIES}
    for entry in faq.FAQ_ENTRIES:
        is_placeholder = entry["answer"].startswith("[ЗАПОЛНИТЬ")
        assert (entry["id"] in usable_ids) != is_placeholder


def test_placeholder_ids_not_offered_to_claude_tool_schema():
    placeholder_ids = {e["id"] for e in faq.FAQ_ENTRIES if e["answer"].startswith("[ЗАПОЛНИТЬ")}
    allowed_ids = set(faq._TOOL["input_schema"]["properties"]["faq_id"]["enum"])
    assert not (placeholder_ids & allowed_ids)


def test_real_entries_answers_have_no_placeholder_marker():
    for entry_id in ("faq_price", "faq_timeline", "faq_who_is_integrator"):
        assert "[ЗАПОЛНИТЬ" not in faq.get_answer(entry_id)


def test_all_entries_filled_no_placeholders_remain():
    """P-003 закрыт — все пункты базы знаний заполнены реальными фактами, ни одного черновика
    "[ЗАПОЛНИТЬ" быть не должно."""
    for entry in faq.FAQ_ENTRIES:
        assert not entry["answer"].startswith("[ЗАПОЛНИТЬ"), entry["id"]
    assert {e["id"] for e in faq._USABLE_ENTRIES} == {e["id"] for e in faq.FAQ_ENTRIES}


def test_no_duplicate_closing_question_in_faq_timeline_and_who_is_integrator():
    """Закрывающий вопрос про передачу кейса на оценку теперь добавляется враппером
    core/templates.py: faq_answer_with_followup ко ВСЕМ ответам — сам answer не должен его
    повторять (иначе клиент увидит один и тот же вопрос дважды в одном сообщении)."""
    for entry_id in ("faq_timeline", "faq_who_is_integrator"):
        assert "передать вашу задачу партнёрам на оценку" not in faq.get_answer(entry_id)
