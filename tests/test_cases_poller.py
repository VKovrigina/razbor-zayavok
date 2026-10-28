import asyncio

from cases import poller
from cases.models import CaseStatus


def _task(task_id, deal_id, text=poller.TRIGGER_TEXT):
    return {"id": task_id, "entity_id": deal_id, "text": text}


async def _async_noop(*args, **kwargs):
    return None


def test_list_trigger_tasks_filters_by_exact_text(monkeypatch):
    monkeypatch.setattr(
        poller.amo_client,
        "list_open_tasks",
        lambda user_id: [
            {"id": 1, "entity_id": 100, "text": poller.TRIGGER_TEXT},
            {"id": 2, "entity_id": 200, "text": poller.TRIGGER_TEXT + " "},  # лишний пробел
            {"id": 3, "entity_id": 300, "text": "другой текст"},
        ],
    )
    tasks = poller.list_trigger_tasks()
    assert [t["id"] for t in tasks] == [1]


def test_process_task_skips_when_task_id_already_in_cases(cases_repo, monkeypatch):
    cases_repo.insert_posted(1, 100)
    calls = []
    monkeypatch.setattr(poller.amo_client, "get_lead", lambda deal_id: calls.append(deal_id))

    asyncio.run(poller.process_task(_task(1, 100)))

    assert calls == []  # дальше guard 1 код не пошёл


def test_process_task_alerts_and_skips_when_active_case_exists_for_deal(cases_repo, monkeypatch):
    cases_repo.insert_posted(1, 100)  # активный кейс POSTED по сделке 100
    sent = []
    monkeypatch.setattr(
        poller.report_webhook,
        "send_error_notification",
        lambda marker, message: sent.append((marker, message)),
    )

    asyncio.run(poller.process_task(_task(2, 100)))

    assert len(sent) == 1
    assert sent[0][0] == "100"
    assert "1" in sent[0][1]  # текст алерта упоминает task_id уже существующего активного кейса
    assert cases_repo.task_exists(2) is False


def test_process_task_does_not_realert_guard2_when_already_alerted(cases_repo, monkeypatch):
    cases_repo.insert_posted(1, 100)
    cases_repo.set_kv(f"{poller._KV_ALERTED_GUARD2_PREFIX}2", "1")
    sent = []
    monkeypatch.setattr(
        poller.report_webhook,
        "send_error_notification",
        lambda marker, message: sent.append(1),
    )

    asyncio.run(poller.process_task(_task(2, 100)))

    assert sent == []


def test_process_task_alerts_and_skips_when_full_spec_empty(cases_repo, monkeypatch):
    monkeypatch.setattr(poller.amo_client, "get_lead", lambda deal_id: {"custom_fields_values": []})
    sent = []
    monkeypatch.setattr(
        poller.report_webhook,
        "send_error_notification",
        lambda marker, message: sent.append((marker, message)),
    )

    asyncio.run(poller.process_task(_task(1, 100)))

    assert len(sent) == 1
    assert "Полное ТЗ" in sent[0][1]
    assert cases_repo.task_exists(1) is False


def test_process_task_does_not_realert_guard3_when_already_alerted(cases_repo, monkeypatch):
    cases_repo.set_kv(f"{poller._KV_ALERTED_GUARD3_PREFIX}1", "1")
    monkeypatch.setattr(poller.amo_client, "get_lead", lambda deal_id: {"custom_fields_values": []})
    sent = []
    monkeypatch.setattr(
        poller.report_webhook,
        "send_error_notification",
        lambda marker, message: sent.append(1),
    )

    asyncio.run(poller.process_task(_task(1, 100)))

    assert sent == []


def _full_spec_lead(text):
    return {
        "custom_fields_values": [
            {"field_id": poller.settings.amocrm_field_id_full_spec, "values": [{"value": text}]}
        ]
    }


def _patch_happy_publish(monkeypatch, calls):
    monkeypatch.setattr(poller.amo_client, "get_lead", lambda deal_id: _full_spec_lead("текст кейса"))

    async def fake_send_message(chat_id, text, reply_markup=None, message_thread_id=None):
        calls.append(("telegram_post", chat_id, text, message_thread_id))

    monkeypatch.setattr(poller.bot, "send_message", fake_send_message)
    monkeypatch.setattr(
        poller.amo_client,
        "update_lead_status",
        lambda deal_id, status_id: calls.append(("stage", deal_id, status_id)),
    )
    monkeypatch.setattr(
        poller.amo_client, "complete_task", lambda task_id: calls.append(("complete_task", task_id))
    )


def test_process_task_clears_alerts_on_successful_publish(cases_repo, monkeypatch):
    cases_repo.set_kv(f"{poller._KV_ALERTED_GUARD2_PREFIX}1", "1")
    cases_repo.set_kv(f"{poller._KV_ALERTED_GUARD3_PREFIX}1", "1")
    _patch_happy_publish(monkeypatch, [])

    asyncio.run(poller.process_task(_task(1, 100)))

    assert not cases_repo.get_kv(f"{poller._KV_ALERTED_GUARD2_PREFIX}1")
    assert not cases_repo.get_kv(f"{poller._KV_ALERTED_GUARD3_PREFIX}1")


def test_process_task_full_publish_sequence_calls_in_order(cases_repo, monkeypatch):
    calls = []
    _patch_happy_publish(monkeypatch, calls)

    asyncio.run(poller.process_task(_task(1, 100)))

    assert cases_repo.task_exists(1) is True  # шаг 1 (вставка) прошёл раньше остальных
    assert [c[0] for c in calls] == ["telegram_post", "stage", "complete_task"]
    assert calls[0][3] == poller.settings.telegram_cases_topic_id  # сообщение в тему "кейсы"
    case = cases_repo.get_case(1)
    assert case.status == CaseStatus.POSTED


def test_process_task_insert_posted_race_returns_without_publishing(cases_repo, monkeypatch):
    # Симулируем гонку: task_id ещё не существует на момент guard 1, но успевает появиться до
    # insert_posted (в реальности недостижимо при строго последовательной обработке — защита).
    cases_repo.insert_posted(1, 100)
    monkeypatch.setattr(poller.repo, "task_exists", lambda task_id: False)
    calls = []
    _patch_happy_publish(monkeypatch, calls)

    asyncio.run(poller.process_task(_task(1, 100)))

    assert calls == []  # публикация не пошла дальше вставки


def test_process_task_publish_step_exception_is_caught_sets_failed_publish(cases_repo, monkeypatch):
    monkeypatch.setattr(poller.amo_client, "get_lead", lambda deal_id: _full_spec_lead("текст"))

    async def failing_send_message(chat_id, text, reply_markup=None, message_thread_id=None):
        raise RuntimeError("telegram недоступен")

    monkeypatch.setattr(poller.bot, "send_message", failing_send_message)
    monkeypatch.setattr(poller.report_webhook, "send_error_notification", lambda marker, message: None)

    asyncio.run(poller.process_task(_task(1, 100)))  # не должно бросить исключение наружу

    case = cases_repo.get_case(1)
    assert case.status == CaseStatus.FAILED_PUBLISH


def test_poll_once_processes_tasks_strictly_sequentially_not_gathered(cases_repo, monkeypatch):
    order = []

    async def fake_process_task(task):
        order.append(f"start:{task['id']}")
        await asyncio.sleep(0)  # даёт event loop'у шанс переключиться, если бы был gather
        order.append(f"end:{task['id']}")

    monkeypatch.setattr(
        poller, "list_trigger_tasks", lambda: [_task(1, 100), _task(2, 200)]
    )
    monkeypatch.setattr(poller, "process_task", fake_process_task)

    asyncio.run(poller.poll_once())

    assert order == ["start:1", "end:1", "start:2", "end:2"]


# --- Пункт 3 аудита 2026-10-28: публикация отдельно от шагов amoCRM, повторы перед алертом ---

import pytest
from aiogram.exceptions import TelegramRetryAfter


@pytest.fixture()
def no_sleep(monkeypatch):
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(poller.asyncio, "sleep", fake_sleep)
    return sleeps


def _flaky(fail_times, calls, name):
    state = {"n": 0}

    def call(*args):
        state["n"] += 1
        calls.append(name)
        if state["n"] <= fail_times:
            raise ConnectionError("Remote end closed connection without response")

    return call


def _alerts(monkeypatch):
    sent = []
    monkeypatch.setattr(poller.report_webhook, "send_error_notification", lambda marker, message: sent.append(message))
    return sent


def test_amo_stage_retried_then_succeeds_without_alert(cases_repo, monkeypatch, no_sleep):
    calls = []
    _patch_happy_publish(monkeypatch, calls)
    monkeypatch.setattr(poller.amo_client, "update_lead_status", _flaky(2, calls, "stage"))
    alerts = _alerts(monkeypatch)

    asyncio.run(poller.process_task(_task(1, 100)))

    assert calls.count("stage") == 3
    assert alerts == []
    assert cases_repo.get_case(1).status == CaseStatus.POSTED


def test_amo_stage_fails_three_times_alerts_keeps_posted_and_completes_task(cases_repo, monkeypatch, no_sleep):
    calls = []
    _patch_happy_publish(monkeypatch, calls)
    monkeypatch.setattr(poller.amo_client, "update_lead_status", _flaky(99, calls, "stage"))
    alerts = _alerts(monkeypatch)

    asyncio.run(poller.process_task(_task(1, 100)))

    assert calls.count("stage") == 3
    assert any(c[0] == "complete_task" for c in calls if isinstance(c, tuple))
    assert len(alerts) == 1 and "этап" in alerts[0]
    assert cases_repo.get_case(1).status == CaseStatus.POSTED


def test_complete_task_fails_three_times_alerts_keeps_posted(cases_repo, monkeypatch, no_sleep):
    calls = []
    _patch_happy_publish(monkeypatch, calls)
    monkeypatch.setattr(poller.amo_client, "complete_task", _flaky(99, calls, "complete"))
    alerts = _alerts(monkeypatch)

    asyncio.run(poller.process_task(_task(1, 100)))

    assert calls.count("complete") == 3
    assert len(alerts) == 1 and "задача" in alerts[0]
    assert cases_repo.get_case(1).status == CaseStatus.POSTED


def test_publish_retry_after_waits_and_retries(cases_repo, monkeypatch, no_sleep):
    calls = []
    _patch_happy_publish(monkeypatch, calls)
    attempts = []

    async def send(chat_id, text, reply_markup=None, message_thread_id=None):
        attempts.append(1)
        if len(attempts) == 1:
            raise TelegramRetryAfter(method=None, message="Flood control", retry_after=7)

    monkeypatch.setattr(poller.bot, "send_message", send)

    asyncio.run(poller.process_task(_task(1, 100)))

    assert len(attempts) == 2 and 7 in no_sleep
    assert cases_repo.get_case(1).status == CaseStatus.POSTED


def test_publish_other_error_not_retried_alert_says_check_group(cases_repo, monkeypatch, no_sleep):
    _patch_happy_publish(monkeypatch, [])
    attempts = []

    async def send(chat_id, text, reply_markup=None, message_thread_id=None):
        attempts.append(1)
        raise TimeoutError("request timeout")

    monkeypatch.setattr(poller.bot, "send_message", send)
    alerts = _alerts(monkeypatch)

    asyncio.run(poller.process_task(_task(1, 100)))

    assert len(attempts) == 1
    assert cases_repo.get_case(1).status == CaseStatus.FAILED_PUBLISH
    assert len(alerts) == 1 and "проверьте группу" in alerts[0]


def test_publish_retry_after_three_times_fails(cases_repo, monkeypatch, no_sleep):
    _patch_happy_publish(monkeypatch, [])

    async def send(chat_id, text, reply_markup=None, message_thread_id=None):
        raise TelegramRetryAfter(method=None, message="Flood control", retry_after=5)

    monkeypatch.setattr(poller.bot, "send_message", send)
    _alerts(monkeypatch)

    asyncio.run(poller.process_task(_task(1, 100)))

    assert cases_repo.get_case(1).status == CaseStatus.FAILED_PUBLISH
