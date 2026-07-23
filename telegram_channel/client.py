from __future__ import annotations

from pathlib import Path

from telethon import TelegramClient

from config import settings

Path(settings.telegram_session_path).parent.mkdir(parents=True, exist_ok=True)

_client: TelegramClient | None = None


def get_client() -> TelegramClient:
    """Ленивая инициализация: TelegramClient должен создаваться уже внутри работающего
    asyncio event loop (после asyncio.run()), иначе Telethon привязывается к другому/старому
    loop'у и соединение рвётся при первом реальном использовании."""
    global _client
    if _client is None:
        _client = TelegramClient(
            settings.telegram_session_path, settings.telegram_api_id, settings.telegram_api_hash
        )
    return _client


async def start() -> None:
    """При первом запуске интерактивно запросит код из SMS/2FA (один раз, дальше сессия
    сохраняется в файл TELEGRAM_SESSION_PATH)."""
    await get_client().start(phone=settings.telegram_phone)
