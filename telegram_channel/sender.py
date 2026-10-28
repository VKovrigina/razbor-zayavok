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


class TelegramPeerNotCachedError(TelegramSendError):
    """Числовой peer_id не резолвится: в кэше сессии нет access_hash этого пользователя."""


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
    except ValueError as e:
        # До реальной попытки отправки не дошло — не тратим дневной лимит (P-017 в BACKLOG.md).
        if isinstance(target, int):
            raise TelegramPeerNotCachedError(f"Пользователь {target} не найден в кэше сессии: {e}") from e
        raise TelegramSendError(f"Некорректный или несуществующий username: {e}") from e
    except (UsernameNotOccupiedError, UsernameInvalidError) as e:
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
    входящих ответов. Бросает TelegramSendError, если отправка невозможна.

    Сразу сохраняет кэш сессии: telethon пишет его на диск раз в минуту, и если процесс
    завершится раньше (остановка через os._exit, падение), access_hash нового клиента теряется —
    дальше писать ему по peer_id нельзя (сделки 40125553, 40179275: месяц без напоминаний)."""
    await _jitter(30, 180)
    peer_id = await _send(username, text)
    try:
        get_client().session.save()
    except Exception:
        logger.exception("Не удалось сохранить кэш Telegram-сессии после первого сообщения")
    return peer_id


async def resolve_peer_id(username: str) -> int:
    """Числовой peer_id по username без отправки — для восстановления сделки, у которой первое
    сообщение ушло, а peer_id сохранить не успели (core/state_machine.py: recover_new_deals)."""
    client = get_client()
    try:
        entity = await asyncio.wait_for(client.get_entity(username), timeout=_TELETHON_CALL_TIMEOUT_SECONDS)
    except (UsernameNotOccupiedError, UsernameInvalidError, ValueError, asyncio.TimeoutError) as e:
        raise TelegramSendError(f"Не удалось найти @{username}: {e!r}") from e
    try:
        client.session.save()
    except Exception:
        logger.exception("Не удалось сохранить кэш Telegram-сессии после поиска @%s", username)
    return entity.id


async def send_reply(peer_id: int, text: str, fallback_username: str | None = None) -> None:
    """Ответ/напоминание по peer_id. Если клиента нет в кэше сессии (см. send_first_contact) —
    повторяем по username: его поиск заново кладёт клиента в кэш."""
    await _jitter(15, 90)
    try:
        await _send(peer_id, text)
    except TelegramPeerNotCachedError:
        if not fallback_username:
            raise
        logger.warning("Пользователь %s не найден в кэше сессии — отправляю по username @%s", peer_id, fallback_username)
        await _send(fallback_username, text)
