from __future__ import annotations

import re
import time

from amo.client import amo_client
from config import settings

# Правила самого Telegram: 5-32 символа, буквы/цифры/подчёркивание, начинается с буквы.
# Нужно, чтобы заглушки вроде "-" (поле в CRM не заполнено) не считались настоящим username —
# иначе они уходят в Telegram-отправку (гарантированно упадёт) и, хуже, в проверку конфликта
# идентификатора клиента, где два случайных клиента с одинаковой заглушкой "склеиваются" в
# одного (см. BACKLOG.md, найдено на проде 2026-07-24).
_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")


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
    value = value.strip()
    return value if _USERNAME_RE.match(value) else None


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
    """«Первичные переговоры» — сразу после отправки первого сообщения, независимо от того,
    ответит клиент или нет (см. core/state_machine.py: process_new_deal)."""
    amo_client.update_lead_status(lead_id, settings.amocrm_stage_negotiations_id)


def move_to_clarification(lead_id: int) -> None:
    """«Уточнение ТЗ» — клиент ответил, идёт классификация ответа (см. handle_incoming_reply)."""
    amo_client.update_lead_status(lead_id, settings.amocrm_stage_clarification_id)


def move_to_silence(lead_id: int) -> None:
    """«Молчание» — отправлено напоминание №1 («ваша заявка актуальна?»), ответа пока нет
    (см. core/state_machine.py: process_scheduler_tick)."""
    amo_client.update_lead_status(lead_id, settings.amocrm_stage_silence_id)


def get_lead_status_id(lead_id: int) -> int | None:
    """Текущий этап сделки в amoCRM — используется шедулером, чтобы не слать напоминания, если
    сделку вручную перевели на другой этап (см. core/state_machine.py)."""
    return amo_client.get_lead(lead_id).get("status_id")


def move_to_manual_review(lead_id: int) -> None:
    """«Ручная проверка» — классификация ответа завершена (positive/negative/ambiguous),
    дальше сделку ведёт человек."""
    amo_client.update_lead_status(lead_id, settings.amocrm_stage_manual_review_id)


def move_to_blocked(lead_id: int) -> None:
    amo_client.update_lead_status(lead_id, settings.amocrm_stage_blocked_id)


def add_note(lead_id: int, text: str) -> None:
    amo_client.create_note(lead_id, text)


def create_manager_task(lead_id: int, text: str, due_in_hours: int = 1) -> None:
    complete_till = int(time.time()) + due_in_hours * 3600
    amo_client.create_task(lead_id, settings.amocrm_varvara_user_id, text, complete_till)


# Теги канала связи — читаются проектом "Выдача кейсов к группу" при передаче контакта клиента
# партнёру (см. его Логика ИИ агента.md, разд. 4). Названия зафиксированы в BACKLOG.md P1-06
# этого проекта.
_CHANNEL_TAG_NAMES = {"telegram": "ТГ", "email": "Почта"}


def set_channel_tag(lead_id: int, channel_value: str) -> None:
    """Ставит тег фактического канала связи с клиентом (см. core/state_machine.py:
    process_new_deal, вызывается сразу после финализации канала)."""
    amo_client.add_lead_tag(lead_id, _CHANNEL_TAG_NAMES[channel_value])


def set_full_spec_field(lead_id: int, text: str) -> None:
    """Записывает собранный текст ТЗ в custom-поле «Полное ТЗ» — источник для проекта "Выдача
    кейсов к группу", который публикует это поле дословно партнёрам (см. core/state_machine.py:
    handle_incoming_reply, ветка POSITIVE)."""
    amo_client.set_lead_custom_field(lead_id, settings.amocrm_field_id_full_spec, text)


def set_messaging_tariff_tag(lead_id: int) -> None:
    """Ставит тег 'Месседжинг' — сделке требуется отдельный тариф на 'операции' (работа с
    сообщениями), см. core/state_machine.py: process_new_deal / handle_incoming_reply (P-052)."""
    amo_client.add_lead_tag(lead_id, "Месседжинг")
