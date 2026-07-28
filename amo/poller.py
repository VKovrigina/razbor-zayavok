from __future__ import annotations

import asyncio
import logging

from amo.actions import create_manager_task, extract_lead_data, move_to_blocked
from amo.client import amo_client
from config import settings
from core import state_machine, templates
from db import repository as repo

logger = logging.getLogger(__name__)


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


async def poll_loop() -> None:
    while True:
        try:
            await poll_once()
        except Exception:
            logger.exception("Ошибка в цикле поллинга amoCRM")
        await asyncio.sleep(settings.amocrm_poll_interval_seconds)
