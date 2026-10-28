from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta

from config import settings
from core import timeutils
from db import repository as repo
from reporting import webhook

logger = logging.getLogger(__name__)

_DIRECTION_LABELS = {
    "in": "Входящее",
    "out": "Исходящее",
    "system": "Событие",
}

_MAX_ACTION_TEXT_LENGTH = 200


def _format_last_action(direction: str, text: str) -> str:
    label = _DIRECTION_LABELS.get(direction, direction)
    text = (text or "").strip()
    if len(text) > _MAX_ACTION_TEXT_LENGTH:
        text = text[:_MAX_ACTION_TEXT_LENGTH] + "…"
    return f"{label}: {text}" if text else label


# Отчёт уходит в фиксированные часы по местному времени (`settings.report_hours_local`, по
# умолчанию 10 и 16, решено 2026-10-28; раньше — раз в 2 часа). Срочные алерты (ошибки, краш,
# токен amoCRM) идут сразу и этим расписанием не затрагиваются.
_KV_LAST_REPORT_AT = "report_last_sent_at"


def next_report_at(now: datetime) -> datetime:
    """Ближайший час отчёта строго позже `now`, в местном времени."""
    local = now.astimezone(timeutils.tz())
    for day_offset in (0, 1):
        day = (local + timedelta(days=day_offset)).date()
        for hour in sorted(settings.report_hours_local):
            slot = datetime.combine(day, time(hour), tzinfo=timeutils.tz())
            if slot > local:
                return slot
    raise RuntimeError("не заданы часы отчёта (REPORT_HOURS)")


def previous_report_slot(now: datetime) -> datetime:
    """Последний час отчёта не позже `now` — начало окна для самого первого отчёта."""
    local = now.astimezone(timeutils.tz())
    for day_offset in (0, -1):
        day = (local + timedelta(days=day_offset)).date()
        for hour in sorted(settings.report_hours_local, reverse=True):
            slot = datetime.combine(day, time(hour), tzinfo=timeutils.tz())
            if slot < local:
                return slot
    raise RuntimeError("не заданы часы отчёта (REPORT_HOURS)")


def run_report_cycle(now: datetime | None = None) -> None:
    """Отчёт по сделкам с активностью с момента прошлого отправленного отчёта (без активности —
    ничего не отправляется, P-014 в BACKLOG.md). Момент сдвигается только после успешной отправки:
    если вебхук не ответил или бот был выключен, следующий отчёт охватит и пропущенное."""
    now = now or timeutils.utcnow()
    since = repo.get_kv(_KV_LAST_REPORT_AT)
    if not since:
        # Самый первый отчёт: фиксируем начало окна до отправки, чтобы неудачная попытка его не
        # потеряла — иначе следующий отчёт считал бы окно от своего предыдущего часа.
        since = timeutils.to_iso(previous_report_slot(now))
        repo.set_kv(_KV_LAST_REPORT_AT, since)
    activity = repo.list_recent_activity(since)
    if activity:
        webhook.send_report(_rows(activity))
    repo.set_kv(_KV_LAST_REPORT_AT, timeutils.to_iso(now))


def _rows(activity: list[dict]) -> list[dict]:
    return [
        {
            "deal_id": str(item["deal_id"]),
            "channel": item["channel"],
            "status": item["status"],
            "last_action": _format_last_action(item["direction"], item["text"]),
            "date": item["date"],
        }
        for item in activity
    ]


async def report_loop() -> None:
    while True:
        wait = (next_report_at(timeutils.utcnow()) - timeutils.utcnow()).total_seconds()
        await asyncio.sleep(max(wait, 0))
        try:
            await asyncio.to_thread(run_report_cycle)
        except Exception:
            logger.exception("Ошибка в цикле отчёта в вебхук")
