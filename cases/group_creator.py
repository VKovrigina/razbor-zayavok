from __future__ import annotations

import asyncio
from pathlib import Path

from telethon import TelegramClient
from telethon.tl.functions.messages import CreateChatRequest, ExportChatInviteRequest
from telethon.tl.types import PeerChat

from config import settings

Path(settings.telegram_cases_session_path).parent.mkdir(parents=True, exist_ok=True)

# Без таймаута telethon-вызов может зависнуть навсегда на "зомби"-соединении (выглядит
# подключённым после сетевого сбоя, но не отвечает на новые запросы) — тот же баг, что чинили в
# telegram_channel/sender.py (P-068). Здесь asyncio.TimeoutError пробрасывается как есть —
# вызывающий код (cases/contact_delivery.py) уже перехватывает любой Exception и переводит кейс
# в FAILED_GROUP_CREATION/FAILED_CONTACT_SEND с алертом, доп. обработка не нужна.
_TELETHON_CALL_TIMEOUT_SECONDS = 30

_client: TelegramClient | None = None


def get_client() -> TelegramClient:
    """Ленивая инициализация (тот же паттерн, что telegram_channel/client.py) — вторая, отдельная
    telethon-сессия того же номера (P-058), не конфликтует с TELEGRAM_SESSION_PATH у main.py."""
    global _client
    if _client is None:
        _client = TelegramClient(
            settings.telegram_cases_session_path, settings.telegram_api_id, settings.telegram_api_hash
        )
    return _client


async def start() -> None:
    await get_client().start(phone=settings.telegram_phone)


async def create_group_with_invite(partner_tg_user_id: int, title: str) -> str:
    """Создаёт групповой чат с партнёром, взявшим кейс, и возвращает invite-ссылку. `title` —
    название группы (решено 2026-07-31: "{ник клиента} & Альбато", см. cases/templates.py:
    group_title).

    Перед КАЖДЫМ вызовом — get_participants(TELEGRAM_GROUP_ID), не только при старте процесса:
    Telethon резолвит InputUser только по закэшированному access_hash, который не появляется
    просто от факта совместного членства в группе — кэш нужно освежать (решено 2026-07-31,
    см. Логика ИИ агента.md разд. 4.А). Процесс долгоживущий без автоперезапуска — состав
    партнёров в группе может измениться после старта."""
    client = get_client()
    await asyncio.wait_for(
        client.get_participants(settings.telegram_group_id), timeout=_TELETHON_CALL_TIMEOUT_SECONDS
    )

    partner_entity = await asyncio.wait_for(
        client.get_input_entity(partner_tg_user_id), timeout=_TELETHON_CALL_TIMEOUT_SECONDS
    )
    result = await asyncio.wait_for(
        client(CreateChatRequest(users=[partner_entity], title=title)),
        timeout=_TELETHON_CALL_TIMEOUT_SECONDS,
    )
    # telethon >=1.4x: CreateChatRequest возвращает messages.InvitedUsers, сам чат — в
    # result.updates.chats (Updates), не result.chats напрямую (найдено на реальном e2e-прогоне
    # 2026-07-31 — более старая версия API отдавала чат прямо в .chats).
    chat_id = result.updates.chats[0].id
    # Голый int резолвится telethon неоднозначно через общий кэш сущностей (может случайно
    # совпасть с уже закэшированным user_id) — базовый групповой чат (не супергруппа/канал)
    # нужно явно оборачивать в PeerChat (найдено на реальном e2e-прогоне 2026-07-31).
    invite = await asyncio.wait_for(
        client(ExportChatInviteRequest(PeerChat(chat_id))), timeout=_TELETHON_CALL_TIMEOUT_SECONDS
    )
    return invite.link


async def send_dm(target: int | str, text: str) -> None:
    """Личное сообщение произвольному пользователю (клиенту — по username из
    AMOCRM_FIELD_ID_TELEGRAM, либо партнёру — по числовому user_id) — вся доставка контакта в
    разделе 4 идёт через эту вторую telethon-сессию, не через aiogram-бота (решено 2026-07-31).
    Тот же паттерн, что telegram_channel/sender.py: сначала get_entity, потом send_message."""
    client = get_client()
    entity = await asyncio.wait_for(client.get_entity(target), timeout=_TELETHON_CALL_TIMEOUT_SECONDS)
    await asyncio.wait_for(client.send_message(entity, text), timeout=_TELETHON_CALL_TIMEOUT_SECONDS)
