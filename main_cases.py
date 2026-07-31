from __future__ import annotations

import asyncio
import logging
import os
import signal

from cases import crash as cases_crash
from cases import group_creator
from cases.bot import bot, dp
from cases.poller import poll_loop as cases_poll_loop
from cases.repository import init_db
from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    filename="data/main_cases.log",
)
logger = logging.getLogger(__name__)


def _mark_clean_shutdown(signum, _frame) -> None:
    """Тот же паттерн, что main.py: SIGTERM/SIGINT — штатная остановка, не в счёт краша.
    `kill -9` этот обработчик не перехватит — останется засчитан как краш, что корректно."""
    logger.info("Получен сигнал %s — штатное завершение main_cases.py", signum)
    try:
        cases_crash.mark_clean_shutdown()
    except Exception:
        logger.exception("Не удалось записать флаг штатного завершения")
    os._exit(0)


async def main() -> None:
    settings.validate_cases()
    init_db()

    signal.signal(signal.SIGTERM, _mark_clean_shutdown)
    signal.signal(signal.SIGINT, _mark_clean_shutdown)

    cases_crash.report_previous_crash_if_any()
    cases_crash.mark_running()

    await group_creator.start()
    logger.info("Вторая telethon-сессия запущена (аккаунт %s)", settings.telegram_phone)

    tasks = [
        asyncio.create_task(cases_poll_loop(), name="cases_poll_loop"),
        # handle_signals=False: по умолчанию aiogram сам ставит обработчики SIGINT/SIGTERM
        # (просто останавливает polling), перекрывая _mark_clean_shutdown выше — тогда флаг
        # bot_running не сбрасывается и процесс не завершается (найдено на реальном e2e-прогоне
        # 2026-07-31). Единый обработчик сигналов — из main_cases.py, как у main.py.
        asyncio.create_task(dp.start_polling(bot, handle_signals=False), name="cases_bot_polling"),
    ]

    logger.info(
        "main_cases.py запущен: поллинг AmoCRM каждые %ss, TELEGRAM_GROUP_ID=%s",
        settings.amocrm_poll_interval_seconds,
        settings.telegram_group_id,
    )

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
