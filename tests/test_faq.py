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
    """FAQ_ENABLED=False (текущее состояние, см. classify/faq.py) — ответы в FAQ_ENTRIES местами
    placeholder, включать нельзя, пока docs/faq-knowledge-base.md не заполнен реальными фактами."""
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
