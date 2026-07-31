from __future__ import annotations

import asyncio
import logging

from amo.actions import _get_field_value
from amo.client import amo_client
from cases import repository as repo
from cases import templates
from cases.bot import bot, case_claim_keyboard
from cases.crash import update_heartbeat
from cases.models import CaseStatus
from config import settings
from reporting import webhook as report_webhook

logger = logging.getLogger(__name__)

TRIGGER_TEXT = "Клиент согласовал условия — оформить задачу/ТЗ по сделке"

_KV_ALERTED_GUARD2_PREFIX = "alerted:guard2:"
_KV_ALERTED_GUARD3_PREFIX = "alerted:guard3:"


def list_trigger_tasks() -> list[dict]:
    """Все незавершённые задачи на Варвару с ТОЧНЫМ текстом-триггером (P-062 — формулировка
    неизменна, exact-match, не contains/regex)."""
    tasks = amo_client.list_open_tasks(settings.amocrm_varvara_user_id)
    return [t for t in tasks if t.get("text") == TRIGGER_TEXT]


def extract_full_spec(lead: dict) -> str | None:
    return _get_field_value(lead, field_id=settings.amocrm_field_id_full_spec)


def _alert_once(kv_prefix: str, task_id: int, deal_id: int, message: str) -> None:
    """Анти-спам: алерт уходит один раз на task_id, пока флаг не снят _clear_alerts (тот же
    паттерн, что P-015 в amo/poller.py: _report_auth_error_once/_clear_auth_error_flag)."""
    key = f"{kv_prefix}{task_id}"
    if repo.get_kv(key):
        return
    repo.set_kv(key, "1")
    try:
        report_webhook.send_error_notification(marker=str(deal_id), message=message)
    except Exception:
        logger.exception("Не удалось отправить алерт по кейсу (task_id=%s)", task_id)


def _clear_alerts(task_id: int) -> None:
    repo.set_kv(f"{_KV_ALERTED_GUARD2_PREFIX}{task_id}", "")
    repo.set_kv(f"{_KV_ALERTED_GUARD3_PREFIX}{task_id}", "")


async def process_task(task: dict) -> None:
    task_id = task["id"]
    deal_id = task["entity_id"]

    # guard 1: обычный дедуп по task_id (раздел 1)
    if await asyncio.to_thread(repo.task_exists, task_id):
        return

    # guard 2: нет другой активной записи по той же сделке (раздел 2)
    active = await asyncio.to_thread(repo.get_active_case_for_deal, deal_id)
    if active is not None:
        await asyncio.to_thread(
            _alert_once,
            _KV_ALERTED_GUARD2_PREFIX,
            task_id,
            deal_id,
            f"Повторный триггер — уже есть активный кейс {active.task_id}",
        )
        return

    lead = await asyncio.to_thread(amo_client.get_lead, deal_id)
    full_spec = extract_full_spec(lead)

    # guard 3: поле «Полное ТЗ» не пусто (раздел 2)
    if not full_spec:
        await asyncio.to_thread(
            _alert_once,
            _KV_ALERTED_GUARD3_PREFIX,
            task_id,
            deal_id,
            "Не заполнено поле «Полное ТЗ» — кейс не опубликован",
        )
        return

    await asyncio.to_thread(_clear_alerts, task_id)

    inserted = await asyncio.to_thread(repo.insert_posted, task_id, deal_id)
    if not inserted:
        return  # гонка: другой цикл поллинга уже вставил эту же задачу

    try:
        text = templates.case_announcement_text(full_spec)
        await bot.send_message(
            settings.telegram_group_id,
            text,
            reply_markup=case_claim_keyboard(task_id),
            message_thread_id=settings.telegram_cases_topic_id,
        )
        await asyncio.to_thread(
            amo_client.update_lead_status, deal_id, settings.amocrm_stage_sent_to_group_id
        )
        await asyncio.to_thread(amo_client.complete_task, task_id)
    except Exception:
        logger.exception("Сбой публикации кейса (task_id=%s, deal_id=%s)", task_id, deal_id)
        # Анти-спам флаг не нужен: guard 1 (task_exists) гарантированно заблокирует повторную
        # обработку этого же task_id на всех следующих циклах — алерт физически не может уйти
        # больше одного раза.
        try:
            await asyncio.to_thread(
                report_webhook.send_error_notification,
                marker=str(deal_id),
                message=f"Не удалось опубликовать кейс (task_id={task_id}) — разобрать вручную",
            )
        except Exception:
            logger.exception("Не удалось отправить алерт о сбое публикации (task_id=%s)", task_id)
        await asyncio.to_thread(repo.set_status, task_id, CaseStatus.FAILED_PUBLISH)


async def poll_once() -> None:
    """Строго последовательно, НЕ asyncio.gather — иначе гонка в guard 2 при двух
    триггер-задачах одной сделки в одном батче (решено 2026-07-31)."""
    tasks = await asyncio.to_thread(list_trigger_tasks)
    for task in tasks:
        await process_task(task)


async def poll_loop() -> None:
    while True:
        try:
            await poll_once()
        except Exception:
            logger.exception("Ошибка в цикле поллинга кейсов")
        try:
            await asyncio.to_thread(update_heartbeat)
        except Exception:
            logger.exception("Не удалось записать heartbeat main_cases.py")
        await asyncio.sleep(settings.amocrm_poll_interval_seconds)
