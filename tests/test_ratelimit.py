import dataclasses

import pytest

from config import settings as base_settings
from telegram_channel import ratelimit


@pytest.fixture()
def rl_settings(monkeypatch):
    test_settings = dataclasses.replace(base_settings, daily_telegram_send_cap=2)
    monkeypatch.setattr("telegram_channel.ratelimit.settings", test_settings)
    return test_settings


def test_is_send_allowed_does_not_increment(monkeypatch, rl_settings):
    monkeypatch.setattr(ratelimit, "is_in_cooldown", lambda: False)
    counts = {"value": 0}
    monkeypatch.setattr(ratelimit.repo, "get_daily_send_count", lambda: counts["value"])

    assert ratelimit.is_send_allowed() is True
    assert ratelimit.is_send_allowed() is True  # повторный вызов — счётчик не менялся
    assert counts["value"] == 0


def test_is_send_allowed_false_when_cap_reached(monkeypatch, rl_settings):
    monkeypatch.setattr(ratelimit, "is_in_cooldown", lambda: False)
    monkeypatch.setattr(ratelimit.repo, "get_daily_send_count", lambda: 2)

    assert ratelimit.is_send_allowed() is False


def test_is_send_allowed_false_when_in_cooldown(monkeypatch, rl_settings):
    monkeypatch.setattr(ratelimit, "is_in_cooldown", lambda: True)
    monkeypatch.setattr(ratelimit.repo, "get_daily_send_count", lambda: 0)

    assert ratelimit.is_send_allowed() is False


def test_record_send_attempt_increments(monkeypatch, rl_settings):
    calls = []
    monkeypatch.setattr(
        ratelimit.repo, "increment_and_check_daily_cap", lambda cap: calls.append(cap)
    )

    ratelimit.record_send_attempt()

    assert calls == [2]
