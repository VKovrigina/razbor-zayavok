from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from calls.models import Call, CallStatus
from config import settings

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connect():
    Path(settings.db_calls_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_calls_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))


def get_call(lead_id: int) -> Call | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM calls WHERE lead_id = ?", (lead_id,)).fetchone()
        return Call.from_row(row) if row else None


def insert_offered(
    lead_id: int,
    contact_id: int | None,
    contact_name: str | None,
    telegram_username: str | None,
    slot_1: datetime,
    slot_2: datetime,
    telegram_peer_id: int | None = None,
) -> bool:
    """Атомарная вставка. Возвращает False, если lead_id уже обработан (дедуп по PRIMARY KEY,
    не ошибка — лид уже был увиден на предыдущем опросе)."""
    ts = now_iso()
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO calls (lead_id, contact_id, contact_name, telegram_username, "
                "telegram_peer_id, status, offered_slot_1, offered_slot_2, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    lead_id,
                    contact_id,
                    contact_name,
                    telegram_username,
                    telegram_peer_id,
                    CallStatus.OFFERED.value,
                    slot_1.isoformat(),
                    slot_2.isoformat(),
                    ts,
                    ts,
                ),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def insert_no_telegram(lead_id: int, contact_id: int | None, contact_name: str | None) -> bool:
    ts = now_iso()
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO calls (lead_id, contact_id, contact_name, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (lead_id, contact_id, contact_name, CallStatus.NO_TELEGRAM.value, ts, ts),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def confirm_slot(lead_id: int, slot: datetime, calendar_event_uid: str) -> bool:
    """Переход OFFERED -> CONFIRMED. Возвращает False, если lead_id неизвестен (запись не
    найдена — сделка не была предложена ранее)."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE calls SET status = ?, confirmed_slot = ?, calendar_event_uid = ?, "
            "updated_at = ? WHERE lead_id = ?",
            (CallStatus.CONFIRMED.value, slot.isoformat(), calendar_event_uid, now_iso(), lead_id),
        )
        return cur.rowcount > 0


def reoffer_slots(lead_id: int, slot_1: datetime, slot_2: datetime) -> bool:
    """Клиент попросил другое время — заменяем пару предложенных слотов, статус остаётся
    OFFERED. Старые слоты автоматически освобождаются (list_reserved_slots читает текущие
    значения полей, не историю)."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE calls SET offered_slot_1 = ?, offered_slot_2 = ?, updated_at = ? "
            "WHERE lead_id = ? AND status = ?",
            (slot_1.isoformat(), slot_2.isoformat(), now_iso(), lead_id, CallStatus.OFFERED.value),
        )
        return cur.rowcount > 0


def list_reserved_slots() -> set[datetime]:
    """Слоты, занятые предложениями (OFFERED, оба варианта) и подтверждёнными встречами
    (CONFIRMED, только выбранный слот — невыбранный вариант из пары освобождается сам собой,
    т.к. читаем текущие значения полей, а не историю)."""
    reserved: set[datetime] = set()
    with _connect() as conn:
        for row in conn.execute(
            "SELECT offered_slot_1, offered_slot_2 FROM calls WHERE status = ?",
            (CallStatus.OFFERED.value,),
        ):
            reserved.add(datetime.fromisoformat(row["offered_slot_1"]))
            reserved.add(datetime.fromisoformat(row["offered_slot_2"]))
        for row in conn.execute(
            "SELECT confirmed_slot FROM calls WHERE status = ?",
            (CallStatus.CONFIRMED.value,),
        ):
            reserved.add(datetime.fromisoformat(row["confirmed_slot"]))
    return reserved


def set_kv(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO kv_store(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_kv(key: str) -> str | None:
    with _connect() as conn:
        row = conn.execute("SELECT value FROM kv_store WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def set_telegram_cooldown(until_iso: str) -> None:
    set_kv("telegram_cooldown_until", until_iso)


def get_telegram_cooldown() -> str | None:
    return get_kv("telegram_cooldown_until")


def increment_and_check_daily_cap(cap: int) -> bool:
    day = datetime.now(timezone.utc).date().isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO send_counters(day, count) VALUES (?, 0) ON CONFLICT(day) DO NOTHING",
            (day,),
        )
        conn.execute("UPDATE send_counters SET count = count + 1 WHERE day = ?", (day,))
        row = conn.execute("SELECT count FROM send_counters WHERE day = ?", (day,)).fetchone()
        return row["count"] <= cap


def get_daily_send_count() -> int:
    day = datetime.now(timezone.utc).date().isoformat()
    with _connect() as conn:
        row = conn.execute("SELECT count FROM send_counters WHERE day = ?", (day,)).fetchone()
        return row["count"] if row else 0
