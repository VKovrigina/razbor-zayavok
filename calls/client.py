from __future__ import annotations

from pathlib import Path

from telethon import TelegramClient

from config import settings

Path(settings.telegram_calls_session_path).parent.mkdir(parents=True, exist_ok=True)

_client: TelegramClient | None = None


def get_client() -> TelegramClient:
    """Третья независимая telethon-сессия того же аккаунта (тот же TELEGRAM_API_ID/API_HASH/
    PHONE, что и main.py/main_cases.py, свой session-файл) — см. telegram_channel/client.py,
    та же ленивая инициализация внутри работающего asyncio event loop."""
    global _client
    if _client is None:
        _client = TelegramClient(
            settings.telegram_calls_session_path, settings.telegram_api_id, settings.telegram_api_hash
        )
    return _client


async def start() -> None:
    """При первом запуске интерактивно запросит код из Telegram (один раз, дальше сессия
    сохраняется в файл TELEGRAM_CALLS_SESSION_PATH)."""
    await get_client().start(phone=settings.telegram_phone)
