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

# Без таймаута telethon-вызов может зависнуть навсегда, если соединение "зомби" (выглядит
# подключённым после сетевого сбоя/авто-реконнекта, но не отвечает на новые запросы) — это вешало
# весь main.py (asyncio.to_thread не спасает: зависает сам await внутри client.get_entity/
# send_message), требуя ручного kill+restart процесса (найдено на реальном проде 2026-09-09,
# трижды за один день). TimeoutError -> TelegramSendError даёт тот же email-фолбэк, что и остальные
# ошибки Telegram, вместо бесконечного зависания.
_TELETHON_CALL_TIMEOUT_SECONDS = 30


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
        entity = await asyncio.wait_for(
            client.get_entity(target), timeout=_TELETHON_CALL_TIMEOUT_SECONDS
        )
    except (UsernameNotOccupiedError, UsernameInvalidError, ValueError) as e:
        # До реальной попытки отправки не дошло — не тратим дневной лимит (P-017 в BACKLOG.md).
        raise TelegramSendError(f"Некорректный или несуществующий username: {e}") from e
    except asyncio.TimeoutError as e:
        raise TelegramSendError(
            f"get_entity завис дольше {_TELETHON_CALL_TIMEOUT_SECONDS}s — соединение, похоже, "
            "в нерабочем состоянии"
        ) from e

    try:
        await asyncio.wait_for(
            client.send_message(entity, text), timeout=_TELETHON_CALL_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError as e:
        # Неизвестно, ушло ли сообщение реально (ответ не дождались) — не тратим дневной лимит,
        # тот же принцип, что для UsernameNotOccupied/PrivacyRestricted выше.
        raise TelegramSendError(
            f"send_message завис дольше {_TELETHON_CALL_TIMEOUT_SECONDS}s — соединение, похоже, "
            "в нерабочем состоянии"
        ) from e
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
