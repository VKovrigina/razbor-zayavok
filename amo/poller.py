from __future__ import annotations

import asyncio
import logging

from amo.actions import create_manager_task, extract_lead_data
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
                "Сделка %s: конфликт идентификатора клиента с уже отслеживаемой сделкой %s",
                deal_id,
                conflict.deal_id,
            )
            repo.mark_failed(deal_id, templates.TASK_TEXT_IDENTITY_CONFLICT)
            await asyncio.to_thread(
                create_manager_task, deal_id, templates.TASK_TEXT_IDENTITY_CONFLICT
            )
            continue

        await state_machine.process_new_deal(deal_id)


async def poll_loop() -> None:
    while True:
        try:
            await poll_once()
        except Exception:
            logger.exception("Ошибка в цикле поллинга amoCRM")
        await asyncio.sleep(settings.amocrm_poll_interval_seconds)
