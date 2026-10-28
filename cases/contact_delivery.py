from __future__ import annotations

import asyncio
import logging

from amo.actions import extract_lead_data, get_field_value
from amo.client import amo_client
from cases import group_creator
from cases import repository as repo
from cases import templates
from cases.amo_retry import amo_with_retries
from cases.models import CaseStatus
from config import settings
from reporting import webhook as report_webhook

logger = logging.getLogger(__name__)

_TAG_TG = "ТГ"
_TAG_EMAIL = "Почта"


async def deliver_contact(task_id: int, deal_id: int, partner_tg_user_id: int) -> None:
    """Раздел 4 Логика ИИ агента.md — ветвление по тегу канала связи (тег уже стоит, main.py
    гарантирует это до того, как сделка попадает в охват этого сценария). Вся доставка — через
    вторую telethon-сессию (cases/group_creator), бот в этом разделе не участвует (решено
    2026-07-31)."""
    try:
        lead = await amo_with_retries(amo_client.get_lead, deal_id, True)
    except Exception:
        # Раньше падало молча (пункт 4 аудита 2026-10-28): кейс закреплён за партнёром, а ни чата,
        # ни контакта, ни алерта.
        logger.exception("Не удалось получить сделку для передачи контакта (task_id=%s)", task_id)
        case = await asyncio.to_thread(repo.get_case, task_id)
        nick = (case.claimed_by_tg_username if case else None) or "партнёр"
        await _alert(
            deal_id,
            f"Кейс взял {nick} (task_id={task_id}), но контакт клиента не передан: не удалось "
            "получить сделку из amoCRM — передайте вручную",
        )
        await asyncio.to_thread(repo.set_status, task_id, CaseStatus.FAILED_CONTACT_SEND)
        return
    tags = {t.get("name") for t in (lead.get("_embedded") or {}).get("tags") or []}

    if _TAG_TG in tags:
        await _deliver_via_telegram(task_id, deal_id, lead, partner_tg_user_id)
    elif _TAG_EMAIL in tags:
        await _deliver_via_email(task_id, deal_id, lead, partner_tg_user_id)
    else:
        # Найдено на реальных сделках 2026-07-31 (не через main.py — тег «ТГ»/«Почта» ставит
        # только core/state_machine.py, сделки, заведённые вручную в воронку Partners, могут его
        # не иметь): тег отсутствует или не равен точным значениям «ТГ»/«Почта» — раньше это тихо
        # не обрабатывалось (инвариант "тег ставится кодом" оказался ненадёжным), взятие кейса
        # оставалось в CLAIMED навсегда без единого сигнала. Теперь — алерт + статус, кейс уходит
        # на ручной разбор, как остальные FAILED_*.
        logger.error(
            "Не удалось определить канал доставки контакта (task_id=%s, deal_id=%s, tags=%s)",
            task_id, deal_id, tags,
        )
        await _alert(
            deal_id,
            f"Не определён канал доставки контакта (тег «ТГ»/«Почта» отсутствует, task_id={task_id}) — передать вручную",
        )
        await asyncio.to_thread(repo.set_status, task_id, CaseStatus.FAILED_CHANNEL_UNKNOWN)


async def _alert(deal_id: int, message: str) -> None:
    try:
        await asyncio.to_thread(report_webhook.send_error_notification, marker=str(deal_id), message=message)
    except Exception:
        logger.exception("Не удалось отправить алерт по передаче контакта (deal_id=%s)", deal_id)


async def _deliver_via_telegram(task_id: int, deal_id: int, lead: dict, partner_tg_user_id: int) -> None:
    try:
        data = await asyncio.to_thread(extract_lead_data, lead)
        case_text = get_field_value(lead, field_id=settings.amocrm_field_id_full_spec)
        client_nick = f"@{data['telegram_username']}" if data["telegram_username"] else "Клиент"
        title = templates.group_title(client_nick)
        link, warnings = await group_creator.create_group_with_invite(
            partner_tg_user_id, title, templates.discussion_chat_intro(case_text)
        )
        for warning in warnings:
            await _alert(deal_id, f"Чат по кейсу создан (task_id={task_id}), но: {warning}")
        await group_creator.send_dm(data["telegram_username"], templates.client_invite_message(link))
        await group_creator.send_dm(
            partner_tg_user_id, templates.partner_invite_message(case_text, link)
        )
        await asyncio.to_thread(repo.set_status, task_id, CaseStatus.GROUP_CREATED)
    except Exception:
        logger.exception("Не удалось создать групповой чат по кейсу (task_id=%s)", task_id)
        await _alert(deal_id, f"Не удалось создать групповой чат по кейсу (task_id={task_id}) — создать вручную")
        await asyncio.to_thread(repo.set_status, task_id, CaseStatus.FAILED_GROUP_CREATION)


async def _deliver_via_email(task_id: int, deal_id: int, lead: dict, partner_tg_user_id: int) -> None:
    try:
        data = await asyncio.to_thread(extract_lead_data, lead)
        case_text = get_field_value(lead, field_id=settings.amocrm_field_id_full_spec)
        message = templates.email_contact_message(case_text, data["contact_name"], data["email_address"])
        await group_creator.send_dm(partner_tg_user_id, message)
        await asyncio.to_thread(repo.set_status, task_id, CaseStatus.CONTACT_SENT)
    except Exception:
        logger.exception("Не удалось передать контакт клиента по кейсу (task_id=%s)", task_id)
        await _alert(deal_id, f"Не удалось передать контакт клиента партнёру по кейсу (task_id={task_id}) — передать вручную")
        await asyncio.to_thread(repo.set_status, task_id, CaseStatus.FAILED_CONTACT_SEND)
