from __future__ import annotations

import time

from amo.client import amo_client
from config import settings


def _get_field_value(entity: dict, field_id: int | None = None, field_code: str | None = None) -> str | None:
    for field in entity.get("custom_fields_values") or []:
        if field_id is not None and field.get("field_id") == field_id:
            values = field.get("values") or []
            return values[0]["value"] if values else None
        if field_code is not None and field.get("field_code") == field_code:
            values = field.get("values") or []
            return values[0]["value"] if values else None
    return None


def _clean_username(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if value.startswith("https://t.me/"):
        value = value[len("https://t.me/"):]
    if value.startswith("@"):
        value = value[1:]
    return value or None


def extract_lead_data(lead: dict) -> dict:
    """Достаёт из сделки и привязанного контакта все поля, нужные для первого сообщения."""
    telegram_username = _get_field_value(lead, field_id=settings.amocrm_field_id_telegram)
    stack_text = _get_field_value(lead, field_id=settings.amocrm_field_id_stack)
    case_text = _get_field_value(lead, field_id=settings.amocrm_field_id_case)

    contacts = (lead.get("_embedded") or {}).get("contacts") or []
    contact_id = contacts[0]["id"] if contacts else None

    contact_name = None
    email_address = None
    if contact_id:
        contact = amo_client.get_contact(contact_id)
        contact_name = contact.get("name")
        email_address = _get_field_value(contact, field_code="EMAIL")

    return {
        "contact_id": contact_id,
        "contact_name": contact_name,
        "telegram_username": _clean_username(telegram_username),
        "email_address": email_address,
        "stack_text": stack_text,
        "case_text": case_text,
    }


def move_to_negotiations(lead_id: int) -> None:
    amo_client.update_lead_status(lead_id, settings.amocrm_stage_negotiations_id)


def move_to_blocked(lead_id: int) -> None:
    amo_client.update_lead_status(lead_id, settings.amocrm_stage_blocked_id)


def create_manager_task(lead_id: int, text: str, due_in_hours: int = 1) -> None:
    complete_till = int(time.time()) + due_in_hours * 3600
    amo_client.create_task(lead_id, settings.amocrm_varvara_user_id, text, complete_till)
