import dataclasses

import pytest

from config import settings as base_settings
from reporting import crash as report_crash
from reporting import reporter, webhook


class _FakeResponse:
    def raise_for_status(self):
        pass


@pytest.fixture()
def webhook_url(monkeypatch):
    test_settings = dataclasses.replace(
        base_settings, report_webhook_url="https://example.com/wh"
    )
    monkeypatch.setattr("reporting.webhook.settings", test_settings)
    return test_settings


@pytest.fixture()
def captured_posts(monkeypatch, webhook_url):
    calls = []

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return _FakeResponse()

    monkeypatch.setattr("reporting.webhook.requests.post", fake_post)
    return calls


def test_send_report_posts_type_report_with_rows(captured_posts):
    rows = [{"deal_id": "1", "channel": "telegram", "status": "NEW", "last_action": "x", "date": "d"}]

    webhook.send_report(rows)

    assert len(captured_posts) == 1
    payload = captured_posts[0]["json"]
    assert payload["type"] == "report"
    assert payload["rows"] == rows


def test_send_error_notification_posts_type_error_with_marker(captured_posts):
    webhook.send_error_notification("AMOCRM ТОКЕН ИСТЁК", "amoCRM API вернул 401")

    assert len(captured_posts) == 1
    payload = captured_posts[0]["json"]
    assert payload["type"] == "error"
    assert payload["rows"][0]["deal_id"] == "AMOCRM ТОКЕН ИСТЁК"
    assert payload["rows"][0]["last_action"] == "amoCRM API вернул 401"


def test_send_crash_notification_posts_marker_row(captured_posts):
    webhook.send_crash_notification("2026-07-30T10:00:00+00:00")

    assert len(captured_posts) == 1
    payload = captured_posts[0]["json"]
    assert payload["type"] == "crash"
    assert payload["rows"][0]["deal_id"] == "БОТ ОТВАЛИЛСЯ"
    assert payload["rows"][0]["date"] == "2026-07-30T10:00:00+00:00"


def test_no_op_when_webhook_url_not_set(monkeypatch):
    test_settings = dataclasses.replace(base_settings, report_webhook_url="")
    monkeypatch.setattr("reporting.webhook.settings", test_settings)
    calls = []
    monkeypatch.setattr(
        "reporting.webhook.requests.post", lambda *a, **kw: calls.append(1)
    )

    webhook.send_report([{"deal_id": "1"}])

    assert calls == []


def test_format_last_action_labels_direction_and_truncates():
    assert reporter._format_last_action("in", "Привет") == "Входящее: Привет"
    assert reporter._format_last_action("out", "Пока") == "Исходящее: Пока"
    assert reporter._format_last_action("system", "FAILED: x") == "Событие: FAILED: x"

    long_text = "а" * 300
    formatted = reporter._format_last_action("in", long_text)
    assert formatted.endswith("…")
    assert len(formatted) < len(long_text)


def test_run_report_cycle_sends_nothing_when_no_activity(monkeypatch, captured_posts):
    monkeypatch.setattr("reporting.reporter.repo.list_recent_activity", lambda since: [])

    reporter.run_report_cycle()

    assert captured_posts == []


def test_run_report_cycle_sends_rows_when_activity_present(monkeypatch, captured_posts):
    monkeypatch.setattr(
        "reporting.reporter.repo.list_recent_activity",
        lambda since: [
            {
                "deal_id": 1,
                "channel": "telegram",
                "status": "AWAITING_REPLY_1",
                "direction": "out",
                "text": "Отправлено первое сообщение",
                "date": "2026-07-30T10:00:00+00:00",
            }
        ],
    )

    reporter.run_report_cycle()

    assert len(captured_posts) == 1
    rows = captured_posts[0]["json"]["rows"]
    assert rows == [
        {
            "deal_id": "1",
            "channel": "telegram",
            "status": "AWAITING_REPLY_1",
            "last_action": "Исходящее: Отправлено первое сообщение",
            "date": "2026-07-30T10:00:00+00:00",
        }
    ]


def test_report_previous_crash_if_any_skips_when_flag_not_set(monkeypatch, captured_posts):
    monkeypatch.setattr("reporting.crash.repo.get_kv", lambda key: None)

    report_crash.report_previous_crash_if_any()

    assert captured_posts == []


def test_report_previous_crash_if_any_sends_when_flag_left_running(monkeypatch, captured_posts):
    values = {"bot_running": "1", "last_heartbeat_at": "2026-07-30T09:00:00+00:00"}
    monkeypatch.setattr("reporting.crash.repo.get_kv", lambda key: values.get(key))

    report_crash.report_previous_crash_if_any()

    assert len(captured_posts) == 1
    payload = captured_posts[0]["json"]
    assert payload["type"] == "crash"
    assert payload["rows"][0]["date"] == "2026-07-30T09:00:00+00:00"


def test_mark_running_and_clean_shutdown_set_kv(monkeypatch):
    calls = []
    monkeypatch.setattr("reporting.crash.repo.set_kv", lambda k, v: calls.append((k, v)))

    report_crash.mark_running()
    report_crash.mark_clean_shutdown()

    assert calls == [("bot_running", "1"), ("bot_running", "0")]
