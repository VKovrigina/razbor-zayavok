from __future__ import annotations

import logging

from cases import repository as repo
from reporting import webhook

logger = logging.getLogger(__name__)

_KV_RUNNING_FLAG = "cases_bot_running"
_KV_LAST_HEARTBEAT = "cases_last_heartbeat_at"


def report_previous_crash_if_any() -> None:
    """Тот же паттерн, что reporting/crash.py у main.py, но на собственном kv_store
    (app_cases.db) — main_cases.py независимый процесс, свой флаг, свой heartbeat."""
    if repo.get_kv(_KV_RUNNING_FLAG) != "1":
        return
    last_seen = repo.get_kv(_KV_LAST_HEARTBEAT)
    logger.error(
        "Обнаружен нештатный выход из предыдущего запуска main_cases.py (last_heartbeat_at=%s)",
        last_seen,
    )
    try:
        webhook.send_crash_notification(last_seen)
    except Exception:
        logger.exception("Не удалось отправить уведомление о краше main_cases.py в вебхук")


def mark_running() -> None:
    repo.set_kv(_KV_RUNNING_FLAG, "1")


def mark_clean_shutdown() -> None:
    repo.set_kv(_KV_RUNNING_FLAG, "0")


def update_heartbeat() -> None:
    repo.set_kv(_KV_LAST_HEARTBEAT, repo.now_iso())
