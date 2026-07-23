"""Разовый скрипт: запрашивает код авторизации Telegram (шаг 1 из 2).
Запускать из корня проекта: python scripts/telegram_login_step1_send_code.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import TelegramClient  # noqa: E402

from config import settings  # noqa: E402

STATE_PATH = os.path.join("data", ".telegram_login_state.json")


async def main() -> None:
    client = TelegramClient(
        settings.telegram_session_path, settings.telegram_api_id, settings.telegram_api_hash
    )
    await client.connect()
    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"ALREADY_AUTHORIZED as {me.first_name} (id={me.id})")
        await client.disconnect()
        return

    sent = await client.send_code_request(settings.telegram_phone)
    os.makedirs("data", exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"phone_code_hash": sent.phone_code_hash}, f)
    print("CODE_SENT")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
