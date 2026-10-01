from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class CallStatus(str, Enum):
    OFFERED = "OFFERED"  # слот(ы) предложены клиенту, ждём ответа
    CONFIRMED = "CONFIRMED"  # клиент подтвердил, событие в календаре создано
    NO_TELEGRAM = "NO_TELEGRAM"  # тг недоступен/приватность — фолбэк-задача создана


# Занимают слоты в next_two_slots() до явного ответа клиента (см. calls/slots.py) —
# по решению пользователя предложенный слот блокируется бессрочно, не только подтверждённый.
SLOT_RESERVING_STATUSES = {CallStatus.OFFERED, CallStatus.CONFIRMED}


@dataclass
class Call:
    lead_id: int
    contact_id: int | None
    contact_name: str | None
    telegram_username: str | None
    telegram_peer_id: int | None
    status: CallStatus
    offered_slot_1: datetime | None
    offered_slot_2: datetime | None
    confirmed_slot: datetime | None
    calendar_event_uid: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row) -> "Call":
        return cls(
            lead_id=row["lead_id"],
            contact_id=row["contact_id"],
            contact_name=row["contact_name"],
            telegram_username=row["telegram_username"],
            telegram_peer_id=row["telegram_peer_id"],
            status=CallStatus(row["status"]),
            offered_slot_1=_parse_dt(row["offered_slot_1"]),
            offered_slot_2=_parse_dt(row["offered_slot_2"]),
            confirmed_slot=_parse_dt(row["confirmed_slot"]),
            calendar_event_uid=row["calendar_event_uid"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
