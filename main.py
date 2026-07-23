from __future__ import annotations

import asyncio
import logging

from amo.poller import poll_loop as amo_poll_loop
from config import settings
from core.scheduler import scheduler_loop
from db.repository import init_db
from email_channel.poller import poll_loop as email_poll_loop
from telegram_channel.client import get_client as get_telegram_client
from telegram_channel.client import start as telegram_start
from telegram_channel.listener import register_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings.validate()
    init_db()

    await telegram_start()
    register_handlers()
    logger.info("Telegram-клиент запущен (аккаунт %s)", settings.telegram_phone)

    tasks = [
        asyncio.create_task(amo_poll_loop(), name="amo_poll_loop"),
        asyncio.create_task(scheduler_loop(), name="scheduler_loop"),
    ]
    if settings.email_imap_host:
        tasks.append(asyncio.create_task(email_poll_loop(), name="email_poll_loop"))
    else:
        logger.warning(
            "EMAIL_IMAP_HOST не задан — email-fallback отключён (входящие письма не обрабатываются)"
        )

    logger.info("Агент запущен: поллинг amoCRM каждые %ss, шедулер каждые %ss",
                settings.amocrm_poll_interval_seconds, settings.scheduler_tick_seconds)

    await asyncio.gather(*tasks, get_telegram_client().disconnected)


if __name__ == "__main__":
    asyncio.run(main())
