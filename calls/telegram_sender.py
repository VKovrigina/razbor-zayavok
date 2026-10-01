from __future__ import annotations

import asyncio
import logging
import random

from telethon.errors import (
    FloodWaitError,
    PeerFloodError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
    UserPrivacyRestrictedError,
)

from calls import ratelimit
from calls.client import get_client

logger = logging.getLogger(__name__)


class TelegramSendError(Exception):
    """Отправка через Telegram невозможна (приватность/несуществующий username/флуд/лимит) —
    вызывающий код должен создать фолбэк-задачу на ручную обработку (см. calls/amo_actions.py:
    create_fallback_task)."""


async def _jitter(low: float, high: float) -> None:
    await asyncio.sleep(random.uniform(low, high))


async def _send(target, text: str) -> int:
    if not ratelimit.is_send_allowed():
        raise TelegramSendError("Достигнут дневной лимит отправок или активен cooldown")

    client = get_client()
    try:
        entity = await client.get_entity(target)
    except (UsernameNotOccupiedError, UsernameInvalidError, ValueError) as e:
        raise TelegramSendError(f"Некорректный или несуществующий username: {e}") from e

    try:
        await client.send_message(entity, text)
    except FloodWaitError as e:
        ratelimit.record_send_attempt()
        ratelimit.set_cooldown(e.seconds)
        logger.warning("FloodWaitError: cooldown на %s сек", e.seconds)
        raise TelegramSendError(f"FloodWait {e.seconds}s") from e
    except PeerFloodError as e:
        ratelimit.record_send_attempt()
        ratelimit.set_cooldown(24 * 3600)
        logger.error("PeerFloodError — ставим все отправки на паузу на 24ч")
        raise TelegramSendError("PeerFlood") from e
    except UserPrivacyRestrictedError as e:
        # Ровно кейс "нет тг/приватность не даёт написать первыми" из Decisions Log.
        raise TelegramSendError("UserPrivacyRestricted") from e
    else:
        ratelimit.record_send_attempt()
        return entity.id


async def send_first_contact(username: str, text: str) -> int:
    """Первое сообщение по username. Возвращает numeric peer_id для последующего сопоставления
    входящих ответов. Бросает TelegramSendError, если отправка невозможна."""
    await _jitter(30, 180)
    return await _send(username, text)


async def send_reply(peer_id: int, text: str) -> None:
    await _jitter(15, 90)
    await _send(peer_id, text)
