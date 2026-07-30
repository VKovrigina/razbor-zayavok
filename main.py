from __future__ import annotations

import asyncio
import logging
import os
import signal

from amo.poller import poll_loop as amo_poll_loop
from config import settings
from core.scheduler import scheduler_loop
from db.repository import init_db
from email_channel.poller import poll_loop as email_poll_loop
from reporting import crash as report_crash
from reporting.reporter import report_loop
from telegram_channel.client import get_client as get_telegram_client
from telegram_channel.client import start as telegram_start
from telegram_channel.listener import register_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _mark_clean_shutdown(signum, _frame) -> None:
    """SIGTERM/SIGINT (Ctrl+C, `kill <pid>`) — штатная остановка, не в счёт P-014: помечаем это,
    чтобы при следующем запуске report_crash.report_previous_crash_if_any() не принял её за
    краш. `kill -9` этот обработчик не перехватит — останется засчитан как краш, что корректно."""
    logger.info("Получен сигнал %s — штатное завершение", signum)
    try:
        report_crash.mark_clean_shutdown()
    except Exception:
        logger.exception("Не удалось записать флаг штатного завершения")
    os._exit(0)


async def main() -> None:
    settings.validate()
    init_db()

    signal.signal(signal.SIGTERM, _mark_clean_shutdown)
    signal.signal(signal.SIGINT, _mark_clean_shutdown)

    report_crash.report_previous_crash_if_any()
    report_crash.mark_running()

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
    if settings.report_webhook_url:
        tasks.append(asyncio.create_task(report_loop(), name="report_loop"))
    else:
        logger.warning(
            "REPORT_WEBHOOK_URL не задан — отчёт о работе бота в вебхук отключён"
        )

    logger.info("Агент запущен: поллинг amoCRM каждые %ss, шедулер каждые %ss",
                settings.amocrm_poll_interval_seconds, settings.scheduler_tick_seconds)

    await asyncio.gather(*tasks, get_telegram_client().disconnected)


if __name__ == "__main__":
    asyncio.run(main())
