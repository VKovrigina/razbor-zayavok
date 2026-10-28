import asyncio

import pytest

from reporting import watchdog


class _Exited(Exception):
    pass


@pytest.fixture()
def fast_watchdog(monkeypatch):
    monkeypatch.setattr(watchdog, "_CHECK_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(watchdog, "_PROBE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(watchdog, "_last_beat", {})
    alerts = []
    monkeypatch.setattr(
        watchdog.webhook, "send_error_notification", lambda marker, message: alerts.append((marker, message))
    )

    def fake_exit(code):
        raise _Exited(code)

    monkeypatch.setattr(watchdog, "_exit", fake_exit)
    return alerts


class _Client:
    def __init__(self, fail=False, hang=False):
        self.fail = fail
        self.hang = hang
        self.calls = 0

    async def get_me(self):
        self.calls += 1
        if self.hang:
            await asyncio.sleep(3600)
        if self.fail:
            raise ConnectionError("Connection to Telegram failed 5 time(s)")
        return object()


def test_stale_loops_reports_only_silent_ones(monkeypatch):
    monkeypatch.setattr(watchdog, "_last_beat", {"amo": 100.0, "scheduler": 990.0})
    assert watchdog.stale_loops({"amo": 600, "scheduler": 600}, now=1000.0) == ["amo"]


def test_beat_refreshes_loop(monkeypatch):
    monkeypatch.setattr(watchdog, "_last_beat", {"amo": 0.0})
    watchdog.beat("amo")
    assert watchdog.stale_loops({"amo": 600}) == []


def test_silent_loop_alerts_and_exits(fast_watchdog, monkeypatch):
    monkeypatch.setattr(watchdog, "_last_beat", {"amo": -10_000.0})
    with pytest.raises(_Exited) as exc:
        asyncio.run(watchdog.watchdog_loop("main.py", {"amo": 60}, _Client()))
    assert exc.value.args == (1,)
    assert fast_watchdog[0][0] == "main.py"
    assert "amo" in fast_watchdog[0][1]


def test_telegram_failing_three_times_exits(fast_watchdog):
    client = _Client(fail=True)
    with pytest.raises(_Exited):
        asyncio.run(watchdog.watchdog_loop("main.py", {}, client))
    assert client.calls == 3
    assert "Telegram" in fast_watchdog[0][1]


def test_telegram_hanging_probe_counts_as_failure(fast_watchdog):
    client = _Client(hang=True)
    with pytest.raises(_Exited):
        asyncio.run(watchdog.watchdog_loop("main_cases.py", {}, client))
    assert client.calls == 3


def test_successful_probe_resets_failure_counter(fast_watchdog, monkeypatch):
    results = iter([True, True, False, True, True, True])

    class Flaky(_Client):
        async def get_me(self):
            self.calls += 1
            if next(results):
                raise ConnectionError("blip")
            return object()

    client = Flaky()
    with pytest.raises(_Exited):
        asyncio.run(watchdog.watchdog_loop("main.py", {}, client))
    assert client.calls == 6  # 2 сбоя → успех сбросил счётчик → ещё 3 сбоя подряд


def test_alert_failure_does_not_prevent_exit(fast_watchdog, monkeypatch):
    def broken_webhook(marker, message):
        raise RuntimeError("webhook down")

    monkeypatch.setattr(watchdog.webhook, "send_error_notification", broken_webhook)
    with pytest.raises(_Exited):
        asyncio.run(watchdog.watchdog_loop("main.py", {}, _Client(fail=True)))
