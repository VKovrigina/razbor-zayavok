from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Status(str, Enum):
    NEW = "NEW"
    AWAITING_REPLY_1 = "AWAITING_REPLY_1"
    AWAITING_REPLY_2 = "AWAITING_REPLY_2"
    CLOSED_NO_REPLY = "CLOSED_NO_REPLY"
    ESCALATED_POSITIVE = "ESCALATED_POSITIVE"
    ESCALATED_NEGATIVE = "ESCALATED_NEGATIVE"
    ESCALATED_AMBIGUOUS = "ESCALATED_AMBIGUOUS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


TERMINAL_ESCALATED_STATUSES = {
    Status.ESCALATED_POSITIVE,
    Status.ESCALATED_NEGATIVE,
    Status.ESCALATED_AMBIGUOUS,
}

# статусы, в которых сделка ждёт ответа/напоминания и может быть "переоткрыта" входящим сообщением
AWAITING_STATUSES = {
    Status.AWAITING_REPLY_1,
    Status.AWAITING_REPLY_2,
    Status.CLOSED_NO_REPLY,
}

# сделка окончательно закрыта для бота — не переоткрывается входящим сообщением, не считается
# "активной" при проверке конфликта идентификатора клиента (см. find_conflicting_active_deal)
INACTIVE_STATUSES = TERMINAL_ESCALATED_STATUSES | {Status.FAILED, Status.BLOCKED}


class Channel(str, Enum):
    TELEGRAM = "telegram"
    EMAIL = "email"


class ReplyCategory(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    AMBIGUOUS = "ambiguous"


@dataclass
class Deal:
    deal_id: int
    contact_id: int | None
    status: Status
    channel: Channel | None
    telegram_username: str | None
    telegram_peer_id: int | None
    email_address: str | None
    contact_name: str | None
    stack_text: str | None
    case_text: str | None
    reminder_count: int
    faq_cycle_count: int
    messaging_tariff_flagged: bool
    next_action_at: str | None
    in_progress: bool
    telegram_send_cooldown_until: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row) -> "Deal":
        return cls(
            deal_id=row["deal_id"],
            contact_id=row["contact_id"],
            status=Status(row["status"]),
            channel=Channel(row["channel"]) if row["channel"] else None,
            telegram_username=row["telegram_username"],
            telegram_peer_id=row["telegram_peer_id"],
            email_address=row["email_address"],
            contact_name=row["contact_name"],
            stack_text=row["stack_text"],
            case_text=row["case_text"],
            reminder_count=row["reminder_count"],
            faq_cycle_count=row["faq_cycle_count"],
            messaging_tariff_flagged=bool(row["messaging_tariff_flagged"]),
            next_action_at=row["next_action_at"],
            in_progress=bool(row["in_progress"]),
            telegram_send_cooldown_until=row["telegram_send_cooldown_until"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
