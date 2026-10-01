from __future__ import annotations

import asyncio
import logging

from calls import amo_actions, booking
from config import settings
from core.timeutils import utcnow

logger = logging.getLogger(__name__)


async def poll_once() -> None:
    """Последовательно, не asyncio.gather — иначе гонка за один и тот же слот между двумя
    новыми лидами в одном батче (list_reserved_slots должен видеть уже сделанные в этом же
    проходе предложения, см. Decisions Log про бессрочную блокировку слота)."""
    leads = await asyncio.to_thread(amo_actions.get_leads_in_stage)
    now = utcnow()
    for lead in leads:
        try:
            result = await booking.offer_slots_for_lead(lead, now)
            logger.info("Лид %s: %s", lead.get("id"), result)
        except Exception:
            logger.exception("Ошибка обработки лида %s", lead.get("id"))


async def poll_loop() -> None:
    while True:
        try:
            await poll_once()
        except Exception:
            logger.exception("Ошибка в цикле поллинга звонков")
        await asyncio.sleep(settings.amocrm_poll_interval_seconds)
