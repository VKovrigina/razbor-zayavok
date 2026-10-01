from __future__ import annotations

from datetime import datetime

from amo.client import amo_client
from config import settings

FALLBACK_TASK_TEXT = "тг недоступен, связаться вручную"


def get_leads_in_stage() -> list[dict]:
    return amo_client.get_leads_in_stage(
        settings.amocrm_calls_pipeline_id, settings.amocrm_calls_stage_primary_contact_id
    )


def move_to_written_in_tg(lead_id: int) -> None:
    amo_client.update_lead_status(lead_id, settings.amocrm_calls_stage_written_in_tg_id)


def move_to_meeting(lead_id: int) -> None:
    amo_client.update_lead_status(lead_id, settings.amocrm_calls_stage_meeting_id)


def create_fallback_task(lead_id: int) -> None:
    """Тг недоступен (нет хендла/приватность) — почта вне скоупа, задача на ручную обработку."""
    complete_till = int(datetime.now().timestamp()) + 3600
    amo_client.create_task(lead_id, settings.amocrm_varvara_user_id, FALLBACK_TASK_TEXT, complete_till)


def create_meeting_task(lead_id: int, meeting_at: datetime) -> None:
    """Дедлайн задачи = время встречи (в дополнение к событию в календаре)."""
    text = f"Встреча с партнером в {meeting_at.strftime('%H:%M')}"
    amo_client.create_task(lead_id, settings.amocrm_varvara_user_id, text, int(meeting_at.timestamp()))
