"""Догонка пропущенных Telegram-сообщений клиентов (P-069 в BACKLOG.md).

Telethon 1.44 после обрыва связи пропущенные сообщения не запрашивает (`_handle_auto_reconnect`:
"TODO Catch-up"), а за время простоя процесса они не приходят вовсе — сообщение клиента теряется,
бот продолжает считать его молчащим (2026-11-06, @emarsovna). Поэтому при старте и раз в
`_INTERVAL_SECONDS` сверяем последние чаты с базой: если последнее сообщение в чате — от клиента,
сделка ждёт ответа, а в `events_log` этого сообщения нет — обрабатываем его как обычный ответ.

Сообщения моложе `_MIN_AGE_SECONDS` не трогаем — их в это время обрабатывает обычный путь
(listener: окно склейки 6 с + ожидание блокировки сделки до 60 с), иначе ответ ушёл бы дважды.
Если последнее сообщение в чате наше (например, Варвара ответила вручную) — тоже не трогаем.
Старше `_MAX_AGE_SECONDS` — тоже: отвечать через несколько дней поздно, такие разбираются вручную.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from db import repository as repo
from db.models import AWAITING_STATUSES, Channel
from reporting import watchdog
from telegram_channel import listener
from telegram_channel.client import get_client

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 5 * 60
_MIN_AGE_SECONDS = 2 * 60
_MAX_AGE_SECONDS = 2 * 24 * 3600  # старее — отвечать поздно, разбирает Варвара
_DIALOGS_LIMIT = 100
_HISTORY_LIMIT = 20
_TELETHON_CALL_TIMEOUT_SECONDS = 30


async def catch_up_once(now: datetime | None = None) -> None:
    from core import state_machine  # локальный импорт — как в listener, избегаем цикла

    now = now or datetime.now(timezone.utc)
    client = get_client()
    dialogs = await asyncio.wait_for(
        client.get_dialogs(limit=_DIALOGS_LIMIT), timeout=_TELETHON_CALL_TIMEOUT_SECONDS
    )
    for dialog in dialogs:
        try:
            if not dialog.is_user or getattr(dialog.entity, "bot", False):
                continue
            last = dialog.message
            if last is None or last.out:
                continue
            age = (now - last.date).total_seconds()
            if age < _MIN_AGE_SECONDS or age > _MAX_AGE_SECONDS:
                continue
            peer_id = dialog.entity.id
            if peer_id in listener._pending:
                continue
            deal = repo.get_deal_by_telegram_peer(peer_id)
            if deal is None or deal.status not in AWAITING_STATUSES:
                continue
            last_ts = repo.get_last_event_ts(deal.deal_id)
            since = datetime.fromisoformat(last_ts) if last_ts else None
            if since is not None and last.date <= since:
                continue

            history = await asyncio.wait_for(
                client.get_messages(dialog.entity, limit=_HISTORY_LIMIT),
                timeout=_TELETHON_CALL_TIMEOUT_SECONDS,
            )
            missed = [
                m.raw_text for m in reversed(history)
                if not m.out and m.raw_text and (since is None or m.date > since)
                and (now - m.date).total_seconds() <= _MAX_AGE_SECONDS
            ]
            if not missed:
                continue
            text = "\n".join(missed)
            logger.warning(
                "Сделка %s: найдено пропущенное сообщение клиента — обрабатываю: %r",
                deal.deal_id, text[:200],
            )
            await state_machine.handle_incoming_reply(deal.deal_id, text, Channel.TELEGRAM)
        except Exception:
            logger.exception("Не удалось проверить чат %s на пропущенные сообщения",
                             getattr(dialog.entity, "id", "?"))


async def catch_up_loop() -> None:
    while True:
        try:
            await catch_up_once()
        except Exception:
            logger.exception("Ошибка в цикле догонки пропущенных Telegram-сообщений")
        watchdog.beat("telegram_catch_up")
        await asyncio.sleep(_INTERVAL_SECONDS)
