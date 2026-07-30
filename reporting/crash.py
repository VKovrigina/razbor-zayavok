from __future__ import annotations

import logging

from db import repository as repo
from reporting import webhook

logger = logging.getLogger(__name__)

_KV_RUNNING_FLAG = "bot_running"
_KV_LAST_HEARTBEAT = "last_heartbeat_at"


def report_previous_crash_if_any() -> None:
    """Если флаг `bot_running` остался '1' с прошлого запуска — значит `mark_clean_shutdown` не
    вызывался (не было SIGTERM/SIGINT) и процесс завершился нештатно (краш, kill -9). Сам краш не
    чинится (P-014 в BACKLOG.md) — только уведомление в вебхук с последним известным heartbeat
    вместо точного момента падения."""
    if repo.get_kv(_KV_RUNNING_FLAG) != "1":
        return
    last_seen = repo.get_kv(_KV_LAST_HEARTBEAT)
    logger.error(
        "Обнаружен нештатный выход из предыдущего запуска (last_heartbeat_at=%s)", last_seen
    )
    try:
        webhook.send_crash_notification(last_seen)
    except Exception:
        logger.exception("Не удалось отправить уведомление о краше в вебхук")


def mark_running() -> None:
    repo.set_kv(_KV_RUNNING_FLAG, "1")


def mark_clean_shutdown() -> None:
    repo.set_kv(_KV_RUNNING_FLAG, "0")


def update_heartbeat() -> None:
    repo.set_kv(_KV_LAST_HEARTBEAT, repo.now_iso())
