"""Разовый скрипт: завершает авторизацию Telegram кодом из SMS (шаг 2 из 2).
Запускать из корня проекта: python scripts/telegram_login_step2_sign_in.py КОД [ПАРОЛЬ_2FA]
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import TelegramClient  # noqa: E402
from telethon.errors import SessionPasswordNeededError  # noqa: E402

from config import settings  # noqa: E402

STATE_PATH = os.path.join("data", ".telegram_login_state.json")


async def main() -> None:
    if len(sys.argv) < 2:
        print("USAGE: python scripts/telegram_login_step2_sign_in.py КОД [ПАРОЛЬ_2FA]")
        return
    code = sys.argv[1]
    password = sys.argv[2] if len(sys.argv) > 2 else None

    with open(STATE_PATH, "r", encoding="utf-8") as f:
        state = json.load(f)

    client = TelegramClient(
        settings.telegram_session_path, settings.telegram_api_id, settings.telegram_api_hash
    )
    await client.connect()
    try:
        await client.sign_in(
            settings.telegram_phone, code, phone_code_hash=state["phone_code_hash"]
        )
    except SessionPasswordNeededError:
        if not password:
            print("NEED_2FA_PASSWORD")
            await client.disconnect()
            return
        await client.sign_in(password=password)

    me = await client.get_me()
    print(f"SIGNED_IN_AS {me.first_name} (id={me.id})")
    os.remove(STATE_PATH)
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
