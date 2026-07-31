import dataclasses

import pytest

from cases import crash as cases_crash
from config import settings as base_settings


class _FakeResponse:
    def raise_for_status(self):
        return None


@pytest.fixture()
def captured_posts(monkeypatch):
    test_settings = dataclasses.replace(base_settings, report_webhook_url="https://example.com/wh")
    monkeypatch.setattr("reporting.webhook.settings", test_settings)
    calls = []

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return _FakeResponse()

    monkeypatch.setattr("reporting.webhook.requests.post", fake_post)
    return calls


def test_report_previous_crash_if_any_sends_notification_when_flag_left_set(monkeypatch, captured_posts):
    values = {"cases_bot_running": "1", "cases_last_heartbeat_at": "2026-07-31T09:00:00+00:00"}
    monkeypatch.setattr("cases.crash.repo.get_kv", lambda key: values.get(key))

    cases_crash.report_previous_crash_if_any()

    assert len(captured_posts) == 1
    assert captured_posts[0]["json"]["type"] == "crash"


def test_report_previous_crash_if_any_noop_on_clean_shutdown(monkeypatch, captured_posts):
    monkeypatch.setattr("cases.crash.repo.get_kv", lambda key: "0")

    cases_crash.report_previous_crash_if_any()

    assert captured_posts == []


def test_mark_running_and_clean_shutdown_set_kv(monkeypatch):
    calls = []
    monkeypatch.setattr("cases.crash.repo.set_kv", lambda k, v: calls.append((k, v)))

    cases_crash.mark_running()
    cases_crash.mark_clean_shutdown()

    assert calls == [("cases_bot_running", "1"), ("cases_bot_running", "0")]


def test_update_heartbeat_writes_timestamp(monkeypatch):
    calls = []
    monkeypatch.setattr("cases.crash.repo.set_kv", lambda k, v: calls.append((k, v)))
    monkeypatch.setattr("cases.crash.repo.now_iso", lambda: "2026-07-31T10:00:00+00:00")

    cases_crash.update_heartbeat()

    assert calls == [("cases_last_heartbeat_at", "2026-07-31T10:00:00+00:00")]
