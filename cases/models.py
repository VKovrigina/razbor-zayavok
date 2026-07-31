from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CaseStatus(str, Enum):
    POSTED = "POSTED"
    CLAIMED = "CLAIMED"
    GROUP_CREATED = "GROUP_CREATED"
    CONTACT_SENT = "CONTACT_SENT"
    FAILED_PUBLISH = "FAILED_PUBLISH"
    FAILED_CRM_UPDATE = "FAILED_CRM_UPDATE"
    FAILED_GROUP_CREATION = "FAILED_GROUP_CREATION"
    FAILED_CONTACT_SEND = "FAILED_CONTACT_SEND"
    FAILED_CHANNEL_UNKNOWN = "FAILED_CHANNEL_UNKNOWN"
    RESOLVED_MANUALLY = "RESOLVED_MANUALLY"


# Активные для guard 2 (разд. 2 Логика ИИ агента.md) — блокируют повторную публикацию кейса по
# той же сделке. Все FAILED_* блокируют до ручного разбора (RESOLVED_MANUALLY снимает блокировку).
ACTIVE_CASE_STATUSES = {
    CaseStatus.POSTED,
    CaseStatus.CLAIMED,
    CaseStatus.FAILED_PUBLISH,
    CaseStatus.FAILED_CRM_UPDATE,
    CaseStatus.FAILED_GROUP_CREATION,
    CaseStatus.FAILED_CONTACT_SEND,
    CaseStatus.FAILED_CHANNEL_UNKNOWN,
}


@dataclass
class Case:
    task_id: int
    deal_id: int
    status: CaseStatus
    claimed_by_tg_user_id: int | None
    claimed_by_tg_username: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row) -> "Case":
        return cls(
            task_id=row["task_id"],
            deal_id=row["deal_id"],
            status=CaseStatus(row["status"]),
            claimed_by_tg_user_id=row["claimed_by_tg_user_id"],
            claimed_by_tg_username=row["claimed_by_tg_username"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
