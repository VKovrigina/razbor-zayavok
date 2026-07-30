from __future__ import annotations

import logging

import requests

from config import settings
from db import repository as repo

logger = logging.getLogger(__name__)


def _post(payload: dict) -> None:
    if not settings.report_webhook_url:
        logger.warning("REPORT_WEBHOOK_URL не задан — отчёт/уведомление в вебхук не отправлены")
        return
    resp = requests.post(settings.report_webhook_url, json=payload, timeout=15)
    resp.raise_for_status()


def send_report(rows: list[dict]) -> None:
    """Периодический отчёт о работе бота (см. reporting/reporter.py) — одна строка на сделку с
    активностью за окно. P-014 в BACKLOG.md."""
    _post({"type": "report", "sent_at": repo.now_iso(), "rows": rows})


def send_error_notification(marker: str, message: str) -> None:
    """Общий канал для явных сбоев вне обычного крашо-детекта (например, P-015 — истёкший/
    отозванный amoCRM-токен) — та же структура, что и send_crash_notification, с произвольным
    маркером в колонке deal_id и текстом ошибки."""
    _post(
        {
            "type": "error",
            "sent_at": repo.now_iso(),
            "rows": [
                {
                    "deal_id": marker,
                    "channel": "",
                    "status": "",
                    "last_action": message,
                    "date": repo.now_iso(),
                }
            ],
        }
    )


def send_crash_notification(last_seen_at: str | None) -> None:
    """Бот обнаружил при старте, что предыдущий запуск не завершился штатно (см.
    reporting/crash.py) — единственный явный сигнал о падении, P-014 в BACKLOG.md
    (сам краш не чинится, только видимость)."""
    _post(
        {
            "type": "crash",
            "sent_at": repo.now_iso(),
            "rows": [
                {
                    "deal_id": "БОТ ОТВАЛИЛСЯ",
                    "channel": "",
                    "status": "",
                    "last_action": "Процесс аварийно завершился (обнаружено при следующем запуске)",
                    "date": last_seen_at or repo.now_iso(),
                }
            ],
        }
    )
