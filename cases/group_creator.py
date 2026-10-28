from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import ChatNotModifiedError
from telethon.tl.functions.account import UpdateNotifySettingsRequest
from telethon.tl.functions.channels import (
    CreateChannelRequest,
    InviteToChannelRequest,
    TogglePreHistoryHiddenRequest,
)
from telethon.tl.functions.messages import (
    ExportChatInviteRequest,
    GetDialogFiltersRequest,
    UpdateDialogFilterRequest,
)
from telethon.tl.types import (
    DialogFilter,
    InputNotifyPeer,
    InputPeerChannel,
    InputPeerNotifySettings,
    TextWithEntities,
)

from config import settings

logger = logging.getLogger(__name__)

Path(settings.telegram_cases_session_path).parent.mkdir(parents=True, exist_ok=True)

# Папка Telegram аккаунта Варвары, куда складываются чаты по кейсам (решено 2026-10-28). Без
# Premium в папке максимум 100 чатов — заполненная папка продолжается следующей «Настройки 2» и
# т.д. (см. _add_to_settings_folder). Без Premium всего до 10 папок — если создать новую не
# выйдет, придёт алерт (см. create_group_with_invite), сам чат при этом создаётся как обычно.
_SETTINGS_FOLDER_TITLE = "Настройки"
_FOLDER_CHATS_LIMIT = 100
_MUTE_FOREVER = 2**31 - 1

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


async def _call(request):
    return await asyncio.wait_for(get_client()(request), timeout=_TELETHON_CALL_TIMEOUT_SECONDS)


async def _add_to_settings_folder(peer: InputPeerChannel) -> None:
    """Кладёт чат в первую папку из ряда «Настройки», «Настройки 2», «Настройки 3»…, где есть
    место; если все заполнены (или папок нет) — создаёт следующую по номеру (решено 2026-10-28)."""
    result = await _call(GetDialogFiltersRequest())
    filters = [f for f in getattr(result, "filters", result) if isinstance(f, DialogFilter)]
    by_title = {getattr(f.title, "text", f.title): f for f in filters}

    number = 1
    while True:
        title = _SETTINGS_FOLDER_TITLE if number == 1 else f"{_SETTINGS_FOLDER_TITLE} {number}"
        folder = by_title.get(title)
        if folder is None:
            used_ids = {f.id for f in filters}
            folder = DialogFilter(
                id=next(i for i in range(2, 256) if i not in used_ids),
                title=TextWithEntities(text=title, entities=[]),
                pinned_peers=[],
                include_peers=[],
                exclude_peers=[],
            )
            break
        if len(folder.include_peers) + len(folder.pinned_peers) < _FOLDER_CHATS_LIMIT:
            break
        number += 1

    folder.include_peers = [*folder.include_peers, peer]
    await _call(UpdateDialogFilterRequest(id=folder.id, filter=folder))


async def create_group_with_invite(
    partner_tg_user_id: int, title: str, intro_text: str
) -> tuple[str, list[str]]:
    """Создаёт чат с партнёром, взявшим кейс, и возвращает (invite-ссылка, предупреждения).
    `title` — название (решено 2026-07-31: "{ник клиента} & Альбато", см. cases/templates.py:
    group_title).

    С 2026-10-28 — супергруппа с открытой историей (клиент, зайдя по ссылке, видит первое
    сообщение `intro_text` с описанием кейса), без уведомлений и в папке «Настройки» аккаунта.
    Создание, приглашение партнёра и ссылка обязательны — их ошибка пробрасывается (кейс уходит в
    FAILED_GROUP_CREATION). Остальные шаги — дополнительные: их ошибка не ломает уже созданный чат,
    а возвращается в списке предупреждений для алерта (см. cases/contact_delivery.py).

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
    result = await _call(CreateChannelRequest(title=title, about="", megagroup=True))
    channel = result.chats[0]
    # Явный InputPeerChannel, а не голый id — голый int telethon резолвит неоднозначно через
    # общий кэш сущностей (найдено на реальном e2e-прогоне 2026-07-31 для базовых чатов).
    peer = InputPeerChannel(channel_id=channel.id, access_hash=channel.access_hash)
    await _call(InviteToChannelRequest(channel=peer, users=[partner_entity]))

    warnings: list[str] = []
    try:
        await _call(TogglePreHistoryHiddenRequest(channel=peer, enabled=False))
    except ChatNotModifiedError:
        pass  # история уже открыта
    except Exception:
        logger.exception("Не удалось открыть историю чата %s", title)
        warnings.append("не удалось открыть историю чата для новых участников")
    try:
        await asyncio.wait_for(client.send_message(peer, intro_text), timeout=_TELETHON_CALL_TIMEOUT_SECONDS)
    except Exception:
        logger.exception("Не удалось отправить вводное сообщение в чат %s", title)
        warnings.append("не удалось отправить в чат сообщение с описанием кейса")
    try:
        await _call(
            UpdateNotifySettingsRequest(
                peer=InputNotifyPeer(peer), settings=InputPeerNotifySettings(mute_until=_MUTE_FOREVER)
            )
        )
    except Exception:
        logger.exception("Не удалось выключить уведомления чата %s", title)
        warnings.append("не удалось выключить уведомления чата")
    try:
        await _add_to_settings_folder(peer)
    except Exception as exc:
        logger.exception("Не удалось добавить чат %s в папку «%s»", title, _SETTINGS_FOLDER_TITLE)
        warnings.append(
            f"не удалось добавить чат в папку «{_SETTINGS_FOLDER_TITLE}» ({exc}) — возможно, "
            "достигнут лимит папок (без Premium до 10)"
        )

    invite = await _call(ExportChatInviteRequest(peer))
    return invite.link, warnings


async def send_dm(target: int | str, text: str) -> None:
    """Личное сообщение произвольному пользователю (клиенту — по username из
    AMOCRM_FIELD_ID_TELEGRAM, либо партнёру — по числовому user_id) — вся доставка контакта в
    разделе 4 идёт через эту вторую telethon-сессию, не через aiogram-бота (решено 2026-07-31).
    Тот же паттерн, что telegram_channel/sender.py: сначала get_entity, потом send_message."""
    client = get_client()
    entity = await asyncio.wait_for(client.get_entity(target), timeout=_TELETHON_CALL_TIMEOUT_SECONDS)
    await asyncio.wait_for(client.send_message(entity, text), timeout=_TELETHON_CALL_TIMEOUT_SECONDS)
