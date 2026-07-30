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

from telegram_channel import ratelimit
from telegram_channel.client import get_client

logger = logging.getLogger(__name__)


class TelegramSendError(Exception):
    """Отправка через Telegram невозможна (приватность/несуществующий username/флуд/лимит) —
    вызывающий код должен переключиться на email-fallback."""


async def _jitter(low: float, high: float) -> None:
    await asyncio.sleep(random.uniform(low, high))


async def _send(target, text: str) -> int:
    if not ratelimit.is_send_allowed():
        raise TelegramSendError("Достигнут дневной лимит отправок или активен cooldown")

    client = get_client()
    try:
        entity = await client.get_entity(target)
    except (UsernameNotOccupiedError, UsernameInvalidError, ValueError) as e:
        # До реальной попытки отправки не дошло — не тратим дневной лимит (P-017 в BACKLOG.md).
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
        logger.error("PeerFloodError — ставим все first-contact отправки на паузу на 24ч")
        raise TelegramSendError("PeerFlood") from e
    except UserPrivacyRestrictedError as e:
        # Реальной доставки не было — не тратим дневной лимит (P-017 в BACKLOG.md).
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
