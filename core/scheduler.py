from __future__ import annotations

import asyncio
import logging

from config import settings
from core import state_machine
from reporting import crash as report_crash

logger = logging.getLogger(__name__)


async def scheduler_loop() -> None:
    while True:
        try:
            await state_machine.process_scheduler_tick()
        except Exception:
            logger.exception("Ошибка в цикле шедулера напоминаний")
        try:
            await asyncio.to_thread(report_crash.update_heartbeat)
        except Exception:
            logger.exception("Не удалось записать heartbeat")
        await asyncio.sleep(settings.scheduler_tick_seconds)
