import dataclasses

from core import checklist
from config import settings as base_settings


def _no_llm(monkeypatch):
    no_key_settings = dataclasses.replace(base_settings, anthropic_api_key="")
    monkeypatch.setattr("core.checklist.settings", no_key_settings)


def test_stack_with_two_services_passes(monkeypatch):
    _no_llm(monkeypatch)
    issues = checklist.assess("amoCRM + Google Sheets", "Синхронизировать новые лиды из форм в CRM")
    assert "stack" not in issues


def test_stack_with_one_service_flagged(monkeypatch):
    _no_llm(monkeypatch)
    assert "stack" in checklist.assess("amoCRM", "Синхронизировать новые лиды из форм в CRM")


def test_stack_empty_flagged(monkeypatch):
    _no_llm(monkeypatch)
    assert "stack" in checklist.assess("", "Синхронизировать новые лиды из форм в CRM")


def test_stack_two_services_various_separators(monkeypatch):
    _no_llm(monkeypatch)
    for stack in ["amoCRM, Telegram", "amoCRM и Telegram", "amoCRM/Telegram", "amoCRM\nTelegram"]:
        assert "stack" not in checklist.assess(stack, "Синхронизировать лиды из форм в CRM")


def test_case_empty_flagged_without_llm(monkeypatch):
    _no_llm(monkeypatch)
    assert "case" in checklist.assess("amoCRM + Sheets", "")


def test_case_short_flagged_without_llm_fallback(monkeypatch):
    _no_llm(monkeypatch)
    assert "case" in checklist.assess("amoCRM + Sheets", "надо")


def test_case_detailed_passes_without_llm_fallback(monkeypatch):
    _no_llm(monkeypatch)
    issues = checklist.assess("amoCRM + Sheets", "Синхронизировать новые лиды из форм сайта в CRM")
    assert "case" not in issues


def test_both_fields_missing(monkeypatch):
    _no_llm(monkeypatch)
    assert checklist.assess(None, None) == ["stack", "case"]
