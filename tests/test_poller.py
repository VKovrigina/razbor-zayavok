import asyncio

from amo import poller
from db.models import Status


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


def test_poll_once_alerts_webhook_when_both_block_steps_fail(repo, monkeypatch):
    """P-041: если и move_to_blocked, и create_manager_task падают при блокировке старой сделки
    (замена новой) — в CRM не остаётся вообще никакого следа. Единственный оставшийся сигнал —
    вебхук."""
    repo.create_deal_new(100, 900, "Иван", "ivan_test", None, "amoCRM", "Старый кейс")

    monkeypatch.setattr(
        poller.amo_client, "get_leads_in_stage", lambda pipeline_id, status_id: [{"id": 200}]
    )
    monkeypatch.setattr(
        poller,
        "extract_lead_data",
        lambda lead: {
            "contact_id": 900,
            "contact_name": "Иван",
            "telegram_username": "ivan_test",
            "email_address": None,
            "stack_text": "amoCRM",
            "case_text": "Новый кейс",
        },
    )

    def failing(*args, **kwargs):
        raise RuntimeError("amoCRM API down")

    monkeypatch.setattr(poller, "move_to_blocked", failing)
    monkeypatch.setattr(poller, "create_manager_task", failing)

    async def fake_process_new_deal(deal_id):
        return None

    monkeypatch.setattr(poller.state_machine, "process_new_deal", fake_process_new_deal)

    sent = []
    monkeypatch.setattr(
        poller.report_webhook,
        "send_error_notification",
        lambda marker, message: sent.append((marker, message)),
    )

    asyncio.run(poller.poll_once())

    old_deal = repo.get_deal(100)
    assert old_deal.status == Status.BLOCKED  # локально всё равно заблокирована
    assert len(sent) == 1
    assert sent[0][0] == "100"
    assert "200" in sent[0][1]


def test_poll_once_does_not_alert_when_at_least_one_block_step_succeeds(repo, monkeypatch):
    repo.create_deal_new(101, 900, "Иван", "ivan_test", None, "amoCRM", "Старый кейс")

    monkeypatch.setattr(
        poller.amo_client, "get_leads_in_stage", lambda pipeline_id, status_id: [{"id": 201}]
    )
    monkeypatch.setattr(
        poller,
        "extract_lead_data",
        lambda lead: {
            "contact_id": 900,
            "contact_name": "Иван",
            "telegram_username": "ivan_test",
            "email_address": None,
            "stack_text": "amoCRM",
            "case_text": "Новый кейс",
        },
    )

    monkeypatch.setattr(poller, "move_to_blocked", lambda deal_id: None)  # успешно

    def failing_task(*args, **kwargs):
        raise RuntimeError("amoCRM API down")

    monkeypatch.setattr(poller, "create_manager_task", failing_task)

    async def fake_process_new_deal(deal_id):
        return None

    monkeypatch.setattr(poller.state_machine, "process_new_deal", fake_process_new_deal)

    sent = []
    monkeypatch.setattr(
        poller.report_webhook,
        "send_error_notification",
        lambda marker, message: sent.append((marker, message)),
    )

    asyncio.run(poller.poll_once())

    assert sent == []  # хотя бы один шаг прошёл — след в CRM остался, алерт не нужен
