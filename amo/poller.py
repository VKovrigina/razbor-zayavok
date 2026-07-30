from __future__ import annotations

import asyncio
import logging

import requests

from amo.actions import create_manager_task, extract_lead_data, move_to_blocked
from amo.client import amo_client
from config import settings
from core import state_machine, templates
from db import repository as repo
from reporting import webhook as report_webhook

logger = logging.getLogger(__name__)

_KV_AUTH_ERROR_REPORTED = "amocrm_auth_error_reported"


async def poll_once() -> None:
    leads = await asyncio.to_thread(
        amo_client.get_leads_in_stage,
        settings.amocrm_pipeline_id,
        settings.amocrm_stage_new_contact_id,
    )
    for lead in leads:
        deal_id = lead["id"]
        if repo.deal_exists(deal_id):
            continue

        try:
            data = await asyncio.to_thread(extract_lead_data, lead)
        except Exception:
            logger.exception("Не удалось прочитать поля сделки %s", deal_id)
            continue

        conflict = repo.find_conflicting_active_deal(
            data["telegram_username"], data["email_address"], exclude_deal_id=deal_id
        )

        repo.create_deal_new(
            deal_id,
            data["contact_id"],
            data["contact_name"],
            data["telegram_username"],
            data["email_address"],
            data["stack_text"],
            data["case_text"],
        )

        if conflict:
            logger.warning(
                "Сделка %s: клиент уже вёл диалог в сделке %s — блокируем старую, работаем с новой",
                deal_id,
                conflict.deal_id,
            )
            try:
                await asyncio.to_thread(move_to_blocked, conflict.deal_id)
            except Exception:
                logger.exception(
                    "Сделка %s: не удалось перевести на этап 'Блок' (замена сделкой %s)",
                    conflict.deal_id,
                    deal_id,
                )
            repo.block_superseded(conflict.deal_id, deal_id)
            try:
                await asyncio.to_thread(
                    create_manager_task, conflict.deal_id, templates.task_text_superseded(deal_id)
                )
            except Exception:
                logger.exception(
                    "Сделка %s: не удалось создать задачу на Варвару (замена сделкой %s)",
                    conflict.deal_id,
                    deal_id,
                )

        await state_machine.process_new_deal(deal_id)


def _report_auth_error_once() -> None:
    """amoCRM API вернул 401 — токен истёк или отозван (P-015 в BACKLOG.md). Раньше это молча
    оседало в логе на каждый тик поллинга; теперь шлём один алерт в вебхук (не при каждой
    попытке) и сбрасываем флаг, как только поллинг снова станет успешным."""
    if repo.get_kv(_KV_AUTH_ERROR_REPORTED) == "1":
        return
    repo.set_kv(_KV_AUTH_ERROR_REPORTED, "1")
    try:
        report_webhook.send_error_notification(
            "AMOCRM ТОКЕН ИСТЁК",
            "amoCRM API вернул 401 — токен истёк или отозван, новые заявки не подхватываются",
        )
    except Exception:
        logger.exception("Не удалось отправить уведомление об ошибке amoCRM-токена в вебхук")


def _clear_auth_error_flag() -> None:
    if repo.get_kv(_KV_AUTH_ERROR_REPORTED) == "1":
        repo.set_kv(_KV_AUTH_ERROR_REPORTED, "0")


async def poll_loop() -> None:
    while True:
        try:
            await poll_once()
            await asyncio.to_thread(_clear_auth_error_flag)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status == 401:
                await asyncio.to_thread(_report_auth_error_once)
            logger.exception("Ошибка в цикле поллинга amoCRM (HTTP %s)", status)
        except Exception:
            logger.exception("Ошибка в цикле поллинга amoCRM")
        await asyncio.sleep(settings.amocrm_poll_interval_seconds)
