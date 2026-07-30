from __future__ import annotations

import asyncio
import logging

from telethon import events

from db import repository as repo
from db.models import Channel
from telegram_channel.client import get_client

logger = logging.getLogger(__name__)

_AGGREGATION_WINDOW_SECONDS = 6
_pending: dict[int, list[str]] = {}


def register_handlers() -> None:
    get_client().add_event_handler(
        _on_new_message, events.NewMessage(incoming=True, func=lambda e: e.is_private)
    )


async def _on_new_message(event) -> None:
    from core import state_machine  # локальный импорт — избегаем цикла на уровне модулей

    sender = await event.get_sender()
    if sender is None or getattr(sender, "bot", False):
        return
    peer_id = sender.id

    deal = repo.get_deal_by_telegram_peer(peer_id)
    if deal is None:
        return  # сообщение не от отслеживаемого клиента — игнорируем

    is_owner = peer_id not in _pending
    _pending.setdefault(peer_id, []).append(event.raw_text or "")
    if not is_owner:
        return  # окно агрегации уже открыто другим вызовом — просто добавили текст

    await asyncio.sleep(_AGGREGATION_WINDOW_SECONDS)
    messages = _pending.pop(peer_id, [])
    full_text = "\n".join(m for m in messages if m)

    try:
        await state_machine.handle_incoming_reply(deal.deal_id, full_text, Channel.TELEGRAM)
    except Exception:
        logger.exception("Ошибка обработки входящего Telegram-сообщения по сделке %s", deal.deal_id)
