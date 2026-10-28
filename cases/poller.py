from __future__ import annotations

import asyncio
import logging

from aiogram.exceptions import TelegramRetryAfter

from amo.actions import get_field_value
from amo.client import amo_client
from cases import repository as repo
from cases.amo_retry import amo_with_retries
from cases import templates
from cases.bot import bot, case_claim_keyboard
from cases.crash import update_heartbeat
from cases.models import CaseStatus
from config import settings
from reporting import watchdog
from reporting import webhook as report_webhook

logger = logging.getLogger(__name__)

TRIGGER_TEXT = "Клиент согласовал условия — оформить задачу/ТЗ по сделке"

_KV_ALERTED_GUARD2_PREFIX = "alerted:guard2:"
_KV_ALERTED_GUARD3_PREFIX = "alerted:guard3:"

_PUBLISH_ATTEMPTS = 3


def list_trigger_tasks() -> list[dict]:
    """Все незавершённые задачи на Варвару с ТОЧНЫМ текстом-триггером (P-062 — формулировка
    неизменна, exact-match, не contains/regex)."""
    tasks = amo_client.list_open_tasks(settings.amocrm_varvara_user_id)
    return [t for t in tasks if t.get("text") == TRIGGER_TEXT]


def extract_full_spec(lead: dict) -> str | None:
    return get_field_value(lead, field_id=settings.amocrm_field_id_full_spec)


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

    # Публикация и шаги amoCRM — раздельно (пункт 3 аудита 2026-10-28): раньше сбой amoCRM ПОСЛЕ
    # публикации ставил FAILED_PUBLISH, хотя кейс уже висел в группе с кнопкой, а взять его можно
    # только из POSTED — каждый партнёр получал «Уже взято». Анти-спам флаги алертов не нужны:
    # guard 1 (task_exists) блокирует повторную обработку task_id.
    try:
        await _publish(templates.case_announcement_text(full_spec), task_id)
    except Exception:
        logger.exception("Сбой публикации кейса (task_id=%s, deal_id=%s)", task_id, deal_id)
        await _alert(
            deal_id,
            f"Не удалось опубликовать кейс (task_id={task_id}) — возможно, сообщение всё же "
            "дошло: проверьте группу перед повторной публикацией",
        )
        await asyncio.to_thread(repo.set_status, task_id, CaseStatus.FAILED_PUBLISH)
        return

    try:
        await amo_with_retries(
            amo_client.update_lead_status, deal_id, settings.amocrm_stage_sent_to_group_id
        )
    except Exception:
        logger.exception("Кейс опубликован, этап сделки не обновлён (task_id=%s)", task_id)
        await _alert(
            deal_id,
            f"Кейс опубликован (task_id={task_id}), но этап сделки в amoCRM не обновлён — "
            "поставить «Отправлено в группу» вручную",
        )
    try:
        await amo_with_retries(amo_client.complete_task, task_id)
    except Exception:
        logger.exception("Кейс опубликован, задача-триггер не закрыта (task_id=%s)", task_id)
        await _alert(
            deal_id,
            f"Кейс опубликован (task_id={task_id}), но задача-триггер в amoCRM не закрыта — "
            "закрыть вручную",
        )


async def _publish(text: str, task_id: int) -> None:
    """Повтор только при RetryAfter — Telegram явно не опубликовал и просит подождать. Остальные
    ошибки (в т.ч. таймаут) не повторяем: сообщение могло дойти, повтор дал бы второй пост."""
    for attempt in range(_PUBLISH_ATTEMPTS):
        try:
            await bot.send_message(
                settings.telegram_group_id,
                text,
                reply_markup=case_claim_keyboard(task_id),
                message_thread_id=settings.telegram_cases_topic_id,
            )
            return
        except TelegramRetryAfter as exc:
            if attempt == _PUBLISH_ATTEMPTS - 1:
                raise
            logger.warning("Публикация кейса %s: RetryAfter %s с", task_id, exc.retry_after)
            await asyncio.sleep(exc.retry_after)


async def _alert(deal_id: int, message: str) -> None:
    try:
        await asyncio.to_thread(
            report_webhook.send_error_notification, marker=str(deal_id), message=message
        )
    except Exception:
        logger.exception("Не удалось отправить алерт (deal_id=%s): %s", deal_id, message)


async def poll_once() -> None:
    """Строго последовательно, НЕ asyncio.gather — иначе гонка в guard 2 при двух
    триггер-задачах одной сделки в одном батче (решено 2026-07-31)."""
    tasks = await asyncio.to_thread(list_trigger_tasks)
    for task in tasks:
        watchdog.beat("cases_poll")
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
        watchdog.beat("cases_poll")
        await asyncio.sleep(settings.amocrm_poll_interval_seconds)
