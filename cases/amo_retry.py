from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

# Сбои amoCRM обычно короткие (обрыв соединения "Remote end closed") — 3 попытки перед алертом
# (решено 2026-10-28). Только для запросов, которые безопасно повторять: чтение сделки, смена
# этапа/поля, закрытие задачи.
_RETRY_DELAYS_SECONDS = (10, 30)


async def amo_with_retries(func, *args):
    for delay in (*_RETRY_DELAYS_SECONDS, None):
        try:
            return await asyncio.to_thread(func, *args)
        except Exception:
            if delay is None:
                raise
            logger.warning("amoCRM: %s%s не прошёл, повтор через %s с", func.__name__, args, delay)
            await asyncio.sleep(delay)
