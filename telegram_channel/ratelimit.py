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


def allow_send() -> bool:
    """Дневной лимит-предохранитель + активный cooldown после FloodWait/PeerFlood."""
    if is_in_cooldown():
        return False
    return repo.increment_and_check_daily_cap(settings.daily_telegram_send_cap)
