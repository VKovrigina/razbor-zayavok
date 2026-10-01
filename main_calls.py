from __future__ import annotations

import asyncio
import logging
import os
import signal

from calls import client as calls_client
from calls.poller import poll_loop
from calls.repository import init_db
from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    filename="data/main_calls.log",
)
logger = logging.getLogger(__name__)


def _mark_clean_shutdown(signum, _frame) -> None:
    logger.info("Получен сигнал %s — штатное завершение main_calls.py", signum)
    os._exit(0)


async def main() -> None:
    settings.validate_calls()
    init_db()

    signal.signal(signal.SIGTERM, _mark_clean_shutdown)
    signal.signal(signal.SIGINT, _mark_clean_shutdown)

    await calls_client.start()
    logger.info("Третья telethon-сессия запущена (аккаунт %s)", settings.telegram_phone)

    logger.info(
        "main_calls.py запущен: поллинг AmoCRM (воронка %s, этап %s) каждые %ss",
        settings.amocrm_calls_pipeline_id,
        settings.amocrm_calls_stage_primary_contact_id,
        settings.amocrm_poll_interval_seconds,
    )

    await poll_loop()


if __name__ == "__main__":
    asyncio.run(main())
