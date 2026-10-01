from __future__ import annotations

import re
from datetime import datetime

import caldav
import icalendar
import recurring_ical_events

from config import settings

CALDAV_URL = "https://caldav.yandex.ru"

_client: caldav.DAVClient | None = None


def get_client() -> caldav.DAVClient:
    global _client
    if _client is None:
        _client = caldav.DAVClient(
            url=CALDAV_URL,
            username=settings.calendar_caldav_login,
            password=settings.calendar_caldav_password,
        )
    return _client


def get_calendar():
    """Календарь для проверки занятости/бронирования — CALENDAR_NAME из настроек, либо первый
    в списке принципала, если имя не задано."""
    principal = get_client().principal()
    calendars = principal.calendars()
    if not calendars:
        raise RuntimeError("У аккаунта не найдено ни одного календаря")
    if not settings.calendar_name:
        return calendars[0]
    for calendar in calendars:
        if calendar.name == settings.calendar_name:
            return calendar
    names = ", ".join(c.name for c in calendars)
    raise RuntimeError(f"Календарь '{settings.calendar_name}' не найден. Доступные: {names}")


def fetch_busy_calendar(calendar) -> icalendar.Calendar:
    """Один сетевой запрос всех событий календаря, смерженных в один icalendar.Calendar для
    последующей локальной проверки занятости через recurring_ical_events (is_slot_free).

    Намеренно НЕ использует caldav.Calendar.date_search() — реальный календарь содержит серии,
    несколько раз отредактированные как "это и все следующие" (типично для Google Calendar),
    из-за чего одна серия расходится на несколько компонентов с похожими UID и собственными
    RRULE. Строгий валидатор внутри caldav.date_search падает на такой структуре (ValueError:
    "Expected a valid recurrence set...") даже для узкого 30-минутного диапазона —
    recurring_ical_events устойчив к этому же входу."""
    vevent_blocks: list[str] = []
    for event in calendar.events():
        raw = event.data
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        vevent_blocks.extend(re.findall(r"BEGIN:VEVENT.*?END:VEVENT", raw, re.S))
    merged = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "\r\n".join(vevent_blocks) + "\r\nEND:VCALENDAR\r\n"
    return icalendar.Calendar.from_ical(merged)


def is_slot_free(busy_calendar: icalendar.Calendar, start: datetime, end: datetime) -> bool:
    return len(recurring_ical_events.of(busy_calendar).between(start, end)) == 0


def create_event(
    calendar,
    summary: str,
    start: datetime,
    end: datetime,
    location: str = "",
    description: str = "",
) -> str:
    ical_kwargs = {"dtstart": start, "dtend": end, "summary": summary}
    if location:
        ical_kwargs["location"] = location
    if description:
        ical_kwargs["description"] = description
    event = calendar.save_event(**ical_kwargs)
    return str(event.icalendar_component.get("uid"))
