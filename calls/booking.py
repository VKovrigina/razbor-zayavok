from __future__ import annotations

from datetime import datetime, timedelta

from amo.client import amo_client
from calls import amo_actions, calendar_client, contact as contact_utils, repository, slots, telegram_sender, templates
from calls.telegram_sender import TelegramSendError
from config import settings

MEETING_DURATION_MINUTES = 30
SEARCH_DAYS_LIMIT = 30


def find_free_pair(
    now: datetime,
    reserved: set[datetime],
    busy_calendar,
    search_days_limit: int = 30,
    meeting_duration_minutes: int = MEETING_DURATION_MINUTES,
) -> tuple[datetime, datetime] | None:
    """Как slots.next_two_slots, но дополнительно проверяет каждый кандидат в реальном
    календаре (calendar_client.is_slot_free) — слот может быть занят там напрямую, без
    предложения через этот процесс (личная встреча, отпуск и т.п.). `busy_calendar` —
    результат calendar_client.fetch_busy_calendar(), а не «живой» caldav-объект."""
    tried = set(reserved)
    max_attempts = search_days_limit * len(slots.SLOT_TIMES) + 1
    for _ in range(max_attempts):
        pair = slots.next_two_slots(now, tried, search_days_limit=search_days_limit)
        if pair is None:
            return None
        busy = {
            candidate
            for candidate in pair
            if not calendar_client.is_slot_free(
                busy_calendar, candidate, candidate + timedelta(minutes=meeting_duration_minutes)
            )
        }
        if not busy:
            return pair
        tried |= busy
    return None


def _lead_contact(lead: dict) -> tuple[int | None, dict]:
    contacts = (lead.get("_embedded") or {}).get("contacts") or []
    contact_id = contacts[0]["id"] if contacts else None
    contact = amo_client.get_contact(contact_id) if contact_id else {}
    return contact_id, contact


async def offer_slots_for_lead(lead: dict, now: datetime) -> str:
    """Один новый лид из этапа «Первичный контакт». Возвращает: 'already_processed' /
    'no_telegram' / 'no_slots' / 'offered'."""
    lead_id = lead["id"]
    if repository.get_call(lead_id) is not None:
        return "already_processed"

    contact_id, contact = _lead_contact(lead)
    contact_name = contact.get("name")
    telegram_username = contact_utils.extract_telegram_username(
        contact, settings.amocrm_calls_contact_field_id_telegram
    )

    if not telegram_username:
        amo_actions.create_fallback_task(lead_id)
        repository.insert_no_telegram(lead_id, contact_id, contact_name)
        return "no_telegram"

    reserved = repository.list_reserved_slots()
    busy_calendar = calendar_client.fetch_busy_calendar(calendar_client.get_calendar())
    pair = find_free_pair(now, reserved, busy_calendar, search_days_limit=SEARCH_DAYS_LIMIT)
    if pair is None:
        amo_actions.create_fallback_task(lead_id)
        return "no_slots"

    name = contact_utils.first_name(contact_name) or "Коллега"
    template_index = templates.next_template_index(repository)
    text = templates.render(
        template_index,
        name=name,
        weekday=templates.weekday_with_date(pair[0].date()),
        slot_1=pair[0].strftime("%H:%M"),
        slot_2=pair[1].strftime("%H:%M"),
    )

    try:
        peer_id = await telegram_sender.send_first_contact(telegram_username, text)
    except TelegramSendError:
        amo_actions.create_fallback_task(lead_id)
        repository.insert_no_telegram(lead_id, contact_id, contact_name)
        return "no_telegram"

    repository.insert_offered(
        lead_id, contact_id, contact_name, telegram_username, pair[0], pair[1], telegram_peer_id=peer_id
    )
    amo_actions.move_to_written_in_tg(lead_id)
    return "offered"


async def confirm_meeting(lead_id: int, chosen_slot: datetime) -> None:
    """Клиент подтвердил слот — вызывается вручную по команде пользователя (см. Decisions Log:
    разбор ответов клиента не автоматизирован)."""
    call = repository.get_call(lead_id)
    calendar = calendar_client.get_calendar()
    end = chosen_slot + timedelta(minutes=MEETING_DURATION_MINUTES)
    title = f"{call.telegram_username or call.contact_name} & Альбато Партнерская программа"

    event_uid = calendar_client.create_event(
        calendar, summary=title, start=chosen_slot, end=end, location=settings.calendar_telemost_link
    )
    repository.confirm_slot(lead_id, chosen_slot, event_uid)
    amo_actions.create_meeting_task(lead_id, chosen_slot)
    amo_actions.move_to_meeting(lead_id)

    summary_text = (
        f"Отлично, договорились! Встреча назначена на {templates.weekday_name(chosen_slot.date())} "
        f"{templates.format_day_month(chosen_slot.date())} в {chosen_slot.strftime('%H:%M')} по МСК.\n"
        f"Ссылка на Телемост: {settings.calendar_telemost_link}"
    )
    if call.telegram_peer_id:
        await telegram_sender.send_reply(call.telegram_peer_id, summary_text)


async def decline_and_reoffer(lead_id: int, now: datetime) -> tuple[datetime, datetime] | None:
    """Клиент попросил другое время — вызывается вручную по команде пользователя."""
    reserved = repository.list_reserved_slots()
    busy_calendar = calendar_client.fetch_busy_calendar(calendar_client.get_calendar())
    pair = find_free_pair(now, reserved, busy_calendar, search_days_limit=SEARCH_DAYS_LIMIT)
    if pair is None:
        return None

    repository.reoffer_slots(lead_id, pair[0], pair[1])
    call = repository.get_call(lead_id)
    text = (
        f"Тогда предложу другое время: в {pair[0].strftime('%H:%M')} или в "
        f"{pair[1].strftime('%H:%M')} по МСК — как вам?"
    )
    if call.telegram_peer_id:
        await telegram_sender.send_reply(call.telegram_peer_id, text)
    return pair
