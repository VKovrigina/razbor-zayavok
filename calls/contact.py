from __future__ import annotations

from amo.actions import clean_username, get_field_value


def extract_telegram_username(contact: dict, field_id: int) -> str | None:
    """Телеграм-хендл из кастомного поля контакта. В этом поле иногда лежит телефон
    (клиент не оставил тг) — clean_username() отбрасывает такие значения, вернётся None."""
    raw = get_field_value(contact, field_id=field_id)
    return clean_username(raw)


def first_name(full_name: str | None) -> str | None:
    if not full_name:
        return None
    parts = full_name.strip().split()
    return parts[0] if parts else None
