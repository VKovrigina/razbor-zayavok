from __future__ import annotations

from datetime import datetime, timedelta, timezone

from calls import repository as repo
from config import settings


def is_in_cooldown() -> bool:
    until = repo.get_telegram_cooldown()
    if not until:
        return False
    return datetime.now(timezone.utc) < datetime.fromisoformat(until)


def set_cooldown(seconds: int) -> None:
    until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    repo.set_telegram_cooldown(until.isoformat())


def is_send_allowed() -> bool:
    """Свой дневной лимит + cooldown — независимо от main.py/main_cases.py (см. Decisions Log:
    полностью отдельный антиспам-счётчик для этого процесса)."""
    if is_in_cooldown():
        return False
    return repo.get_daily_send_count() < settings.daily_telegram_calls_send_cap


def record_send_attempt() -> None:
    repo.increment_and_check_daily_cap(settings.daily_telegram_calls_send_cap)
