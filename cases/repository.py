from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from cases.models import ACTIVE_CASE_STATUSES, Case, CaseStatus
from config import settings

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connect():
    Path(settings.db_cases_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_cases_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))


def task_exists(task_id: int) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM cases WHERE task_id = ?", (task_id,)).fetchone()
        return row is not None


def get_active_case_for_deal(deal_id: int) -> Case | None:
    active_values = [s.value for s in ACTIVE_CASE_STATUSES]
    placeholders = ",".join("?" * len(active_values))
    with _connect() as conn:
        row = conn.execute(
            f"SELECT * FROM cases WHERE deal_id = ? AND status IN ({placeholders}) "
            "ORDER BY created_at DESC LIMIT 1",
            (deal_id, *active_values),
        ).fetchone()
        return Case.from_row(row) if row else None


def get_case(task_id: int) -> Case | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM cases WHERE task_id = ?", (task_id,)).fetchone()
        return Case.from_row(row) if row else None


def insert_posted(task_id: int, deal_id: int) -> bool:
    """Атомарная вставка новой строки со статусом POSTED. Возвращает False, если task_id уже
    существует (UNIQUE(task_id) через PRIMARY KEY) — обычный дедуп, не ошибка."""
    ts = now_iso()
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO cases (task_id, deal_id, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (task_id, deal_id, CaseStatus.POSTED.value, ts, ts),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def claim_case(task_id: int, tg_user_id: int, tg_username: str) -> bool:
    """Атомарный CAS-лок — тот же паттерн, что db.repository.try_lock. Возвращает False, если
    кейс уже не в статусе POSTED (взят кем-то другим или не существует)."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE cases SET status = ?, claimed_by_tg_user_id = ?, claimed_by_tg_username = ?, "
            "updated_at = ? WHERE task_id = ? AND status = ?",
            (
                CaseStatus.CLAIMED.value,
                tg_user_id,
                tg_username,
                now_iso(),
                task_id,
                CaseStatus.POSTED.value,
            ),
        )
        return cur.rowcount > 0


def set_status(task_id: int, status: CaseStatus) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE cases SET status = ?, updated_at = ? WHERE task_id = ?",
            (status.value, now_iso(), task_id),
        )


def set_kv(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS kv_store (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO kv_store(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_kv(key: str) -> str | None:
    with _connect() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS kv_store (key TEXT PRIMARY KEY, value TEXT)")
        row = conn.execute("SELECT value FROM kv_store WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None
