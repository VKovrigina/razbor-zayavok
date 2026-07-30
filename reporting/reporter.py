from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

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


def run_report_cycle() -> None:
    """Раз в `settings.report_interval_seconds` — отчёт по сделкам с реальной активностью за это
    окно (без активности — ничего не отправляется, P-014 в BACKLOG.md)."""
    since = timeutils.to_iso(timeutils.utcnow() - timedelta(seconds=settings.report_interval_seconds))
    activity = repo.list_recent_activity(since)
    if not activity:
        return
    rows = [
        {
            "deal_id": str(item["deal_id"]),
            "channel": item["channel"],
            "status": item["status"],
            "last_action": _format_last_action(item["direction"], item["text"]),
            "date": item["date"],
        }
        for item in activity
    ]
    webhook.send_report(rows)


async def report_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(run_report_cycle)
        except Exception:
            logger.exception("Ошибка в цикле отчёта в вебхук")
        await asyncio.sleep(settings.report_interval_seconds)
