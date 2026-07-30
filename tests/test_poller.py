from amo import poller


def test_report_auth_error_once_sends_and_sets_flag(monkeypatch):
    kv = {}
    monkeypatch.setattr(poller.repo, "get_kv", lambda key: kv.get(key))
    monkeypatch.setattr(poller.repo, "set_kv", lambda key, value: kv.__setitem__(key, value))
    sent = []
    monkeypatch.setattr(
        poller.report_webhook, "send_error_notification", lambda marker, message: sent.append((marker, message))
    )

    poller._report_auth_error_once()

    assert kv[poller._KV_AUTH_ERROR_REPORTED] == "1"
    assert len(sent) == 1
    assert sent[0][0] == "AMOCRM ТОКЕН ИСТЁК"


def test_report_auth_error_once_does_not_duplicate(monkeypatch):
    kv = {poller._KV_AUTH_ERROR_REPORTED: "1"}
    monkeypatch.setattr(poller.repo, "get_kv", lambda key: kv.get(key))
    monkeypatch.setattr(poller.repo, "set_kv", lambda key, value: kv.__setitem__(key, value))
    sent = []
    monkeypatch.setattr(
        poller.report_webhook, "send_error_notification", lambda marker, message: sent.append(1)
    )

    poller._report_auth_error_once()

    assert sent == []  # уже отправлено раньше — повторно не шлём


def test_clear_auth_error_flag_resets_when_set(monkeypatch):
    kv = {poller._KV_AUTH_ERROR_REPORTED: "1"}
    monkeypatch.setattr(poller.repo, "get_kv", lambda key: kv.get(key))
    monkeypatch.setattr(poller.repo, "set_kv", lambda key, value: kv.__setitem__(key, value))

    poller._clear_auth_error_flag()

    assert kv[poller._KV_AUTH_ERROR_REPORTED] == "0"


def test_clear_auth_error_flag_noop_when_not_set(monkeypatch):
    kv = {}
    monkeypatch.setattr(poller.repo, "get_kv", lambda key: kv.get(key))
    calls = []
    monkeypatch.setattr(poller.repo, "set_kv", lambda key, value: calls.append((key, value)))

    poller._clear_auth_error_flag()

    assert calls == []
