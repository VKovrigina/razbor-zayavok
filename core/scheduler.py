from __future__ import annotations

import asyncio
import logging

from config import settings
from core import state_machine

logger = logging.getLogger(__name__)


async def scheduler_loop() -> None:
    while True:
        try:
            await state_machine.process_scheduler_tick()
        except Exception:
            logger.exception("Ошибка в цикле шедулера напоминаний")
        await asyncio.sleep(settings.scheduler_tick_seconds)
