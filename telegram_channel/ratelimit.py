from __future__ import annotations

from datetime import datetime, timedelta, timezone

from config import settings
from db import repository as repo


def is_in_cooldown() -> bool:
    until = repo.get_telegram_cooldown()
    if not until:
        return False
    return datetime.now(timezone.utc) < datetime.fromisoformat(until)


def set_cooldown(seconds: int) -> None:
    until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    repo.set_telegram_cooldown(until.isoformat())


def is_send_allowed() -> bool:
    """Дневной лимит-предохранитель + активный cooldown после FloodWait/PeerFlood — проверка
    БЕЗ инкремента (P-017 в BACKLOG.md). Инкремент — отдельно, в record_send_attempt(), только
    по факту реальной попытки отправки, чтобы ошибки резолва получателя (невалидный username,
    приватность) не тратили лимит впустую."""
    if is_in_cooldown():
        return False
    return repo.get_daily_send_count() < settings.daily_telegram_send_cap


def record_send_attempt() -> None:
    """Считать реальную попытку против дневного лимита — вызывать только когда запрос
    действительно дошёл до Telegram (успех, FloodWait, PeerFlood), НЕ при ошибках резолва
    получателя (P-017 в BACKLOG.md)."""
    repo.increment_and_check_daily_cap(settings.daily_telegram_send_cap)
