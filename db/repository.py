from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from config import settings
from db.models import AWAITING_STATUSES, Channel, Deal, INACTIVE_STATUSES, Status

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connect():
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
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
        _migrate_add_faq_cycle_count(conn)
        _migrate_add_messaging_tariff_flag(conn)
        _migrate_add_clarification_asked(conn)


def _migrate_add_faq_cycle_count(conn: sqlite3.Connection) -> None:
    """`CREATE TABLE IF NOT EXISTS` в schema.sql не добавляет новые колонки в уже существующую
    таблицу — на боевой БД, созданной до появления `faq_cycle_count`, колонки не будет без явного
    ALTER TABLE."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(deals)")}
    if "faq_cycle_count" not in columns:
        conn.execute("ALTER TABLE deals ADD COLUMN faq_cycle_count INTEGER NOT NULL DEFAULT 0")


def _migrate_add_messaging_tariff_flag(conn: sqlite3.Connection) -> None:
    """Как и `_migrate_add_faq_cycle_count` — на боевой БД, созданной до появления этой колонки,
    её не будет без явного ALTER TABLE (P-052 в BACKLOG.md)."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(deals)")}
    if "messaging_tariff_flagged" not in columns:
        conn.execute(
            "ALTER TABLE deals ADD COLUMN messaging_tariff_flagged INTEGER NOT NULL DEFAULT 0"
        )


def _migrate_add_clarification_asked(conn: sqlite3.Connection) -> None:
    """Как и `_migrate_add_faq_cycle_count` — на боевой БД, созданной до появления этой колонки,
    её не будет без явного ALTER TABLE."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(deals)")}
    if "clarification_asked" not in columns:
        conn.execute("ALTER TABLE deals ADD COLUMN clarification_asked INTEGER NOT NULL DEFAULT 0")


# ---------------------------------------------------------------------------
# Создание / чтение сделок
# ---------------------------------------------------------------------------

def get_deal(deal_id: int) -> Deal | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM deals WHERE deal_id = ?", (deal_id,)).fetchone()
        return Deal.from_row(row) if row else None


def deal_exists(deal_id: int) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM deals WHERE deal_id = ?", (deal_id,)).fetchone()
        return row is not None


def find_conflicting_active_deal(
    telegram_username: str | None, email_address: str | None, exclude_deal_id: int | None = None
) -> Deal | None:
    """Ищет уже отслеживаемую сделку с тем же идентификатором клиента (username/email),
    которая ещё не находится в финальном "решённом" состоянии (см. INACTIVE_STATUSES).
    Нужно, чтобы не вести два параллельных автоматических диалога с одним и тем же человеком —
    иначе входящее сообщение в Telegram/письмо невозможно однозначно привязать к сделке."""
    done = tuple(s.value for s in INACTIVE_STATUSES)
    placeholders = ",".join("?" for _ in done)
    clauses = []
    params: list = []
    if telegram_username:
        clauses.append("telegram_username = ?")
        params.append(telegram_username)
    if email_address:
        clauses.append("email_address = ?")
        params.append(email_address)
    if not clauses:
        return None
    query = (
        f"SELECT * FROM deals WHERE ({' OR '.join(clauses)}) "
        f"AND status NOT IN ({placeholders})"
    )
    params.extend(done)
    if exclude_deal_id is not None:
        query += " AND deal_id != ?"
        params.append(exclude_deal_id)
    with _connect() as conn:
        row = conn.execute(query, params).fetchone()
        return Deal.from_row(row) if row else None


def create_deal_new(
    deal_id: int,
    contact_id: int | None,
    contact_name: str | None,
    telegram_username: str | None,
    email_address: str | None,
    stack_text: str | None,
    case_text: str | None,
) -> None:
    """Заводит сделку сразу с флагом канала: если в CRM указан Telegram-username — канал
    'telegram', иначе 'email'. Флаг ставится СРАЗУ, до какой-либо попытки отправки — это нужно,
    чтобы входящее письмо, пришедшее, пока идёт долгая антибан-пауза перед первой Telegram-
    отправкой, не запускало полный сценарий по почте параллельно с Telegram (см. P-007 в
    BACKLOG.md, `email_channel/poller.py`). Если отправка в Telegram в итоге не удастся и бот
    реально перейдёт на email — `set_awaiting_first_sent` перезапишет канал на актуальный."""
    ts = now_iso()
    channel = Channel.TELEGRAM if telegram_username else Channel.EMAIL
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO deals (
                deal_id, contact_id, status, channel, telegram_username, telegram_peer_id,
                email_address, contact_name, stack_text, case_text, reminder_count,
                faq_cycle_count, next_action_at, in_progress, telegram_send_cooldown_until,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, 0, 0, NULL, 0, NULL, ?, ?)
            """,
            (
                deal_id,
                contact_id,
                Status.NEW.value,
                channel.value,
                telegram_username,
                email_address,
                contact_name,
                stack_text,
                case_text,
                ts,
                ts,
            ),
        )


def mark_failed(deal_id: int, reason: str) -> None:
    ts = now_iso()
    with _connect() as conn:
        conn.execute(
            "UPDATE deals SET status = ?, in_progress = 0, updated_at = ? WHERE deal_id = ?",
            (Status.FAILED.value, ts, deal_id),
        )
    log_event(deal_id, "system", None, f"FAILED: {reason}")


def set_awaiting_first_sent(
    deal_id: int, channel: str, telegram_peer_id: int | None, next_action_at: str
) -> None:
    ts = now_iso()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE deals
            SET status = ?, channel = ?, telegram_peer_id = ?, next_action_at = ?,
                reminder_count = 0, in_progress = 0, updated_at = ?
            WHERE deal_id = ?
            """,
            (Status.AWAITING_REPLY_1.value, channel, telegram_peer_id, next_action_at, ts, deal_id),
        )


def advance_to_reminder2(deal_id: int, next_action_at: str) -> None:
    ts = now_iso()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE deals
            SET status = ?, reminder_count = reminder_count + 1, next_action_at = ?,
                in_progress = 0, updated_at = ?
            WHERE deal_id = ?
            """,
            (Status.AWAITING_REPLY_2.value, next_action_at, ts, deal_id),
        )


def close_no_reply(deal_id: int) -> None:
    ts = now_iso()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE deals
            SET status = ?, next_action_at = NULL, in_progress = 0, updated_at = ?
            WHERE deal_id = ?
            """,
            (Status.CLOSED_NO_REPLY.value, ts, deal_id),
        )


def block_superseded(deal_id: int, new_deal_id: int) -> None:
    """Клиент прислал НОВУЮ заявку, пока эта ещё активна — старую считаем окончательно закрытой
    (в отличие от CLOSED_NO_REPLY, эта сделка НЕ переоткрывается входящим сообщением, см.
    INACTIVE_STATUSES) и работаем дальше только с новой (см. amo/poller.py)."""
    ts = now_iso()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE deals
            SET status = ?, next_action_at = NULL, in_progress = 0, updated_at = ?
            WHERE deal_id = ?
            """,
            (Status.BLOCKED.value, ts, deal_id),
        )
    log_event(deal_id, "system", None, f"Заблокирована: заменена новой заявкой {new_deal_id}")


def escalate(deal_id: int, status: Status) -> None:
    ts = now_iso()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE deals
            SET status = ?, next_action_at = NULL, in_progress = 0, updated_at = ?
            WHERE deal_id = ?
            """,
            (status.value, ts, deal_id),
        )


def set_telegram_peer_id(deal_id: int, peer_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE deals SET telegram_peer_id = ?, updated_at = ? WHERE deal_id = ?",
            (peer_id, now_iso(), deal_id),
        )


def set_messaging_tariff_flagged(deal_id: int, value: bool) -> None:
    """Помечает сделку как требующую отдельного тарифа на 'операции' (работа с сообщениями) —
    см. core/state_machine.py: process_new_deal / handle_incoming_reply, P-052 в BACKLOG.md."""
    with _connect() as conn:
        conn.execute(
            "UPDATE deals SET messaging_tariff_flagged = ?, updated_at = ? WHERE deal_id = ?",
            (int(value), now_iso(), deal_id),
        )


def set_clarification_asked(deal_id: int, value: bool) -> None:
    """Помечает, что бот уже один раз переспрашивал недостающие детали задачи при позитивном
    ответе клиента — см. core/state_machine.py: handle_incoming_reply. Не более одного раза за
    сделку, чтобы не зациклиться, если клиент так и не добавит деталей."""
    with _connect() as conn:
        conn.execute(
            "UPDATE deals SET clarification_asked = ?, updated_at = ? WHERE deal_id = ?",
            (int(value), now_iso(), deal_id),
        )


# ---------------------------------------------------------------------------
# Поиск по идентификатору отправителя (входящие сообщения)
# ---------------------------------------------------------------------------

def get_deal_by_telegram_peer(peer_id: int) -> Deal | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM deals WHERE telegram_peer_id = ? ORDER BY created_at DESC LIMIT 1",
            (peer_id,),
        ).fetchone()
        return Deal.from_row(row) if row else None


def get_deal_by_email(email_address: str) -> Deal | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM deals WHERE email_address = ? ORDER BY created_at DESC LIMIT 1",
            (email_address,),
        ).fetchone()
        return Deal.from_row(row) if row else None


# ---------------------------------------------------------------------------
# Шедулер: строки, которым пора отправить напоминание/закрытие
# ---------------------------------------------------------------------------

def list_due_rows(now_iso_value: str) -> list[Deal]:
    statuses = tuple(
        s.value
        for s in AWAITING_STATUSES
        if s not in (Status.CLOSED_NO_REPLY, Status.CLOSED_NOT_RELEVANT)
    )
    placeholders = ",".join("?" for _ in statuses)
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM deals
            WHERE status IN ({placeholders})
              AND next_action_at IS NOT NULL
              AND next_action_at <= ?
              AND in_progress = 0
            """,
            (*statuses, now_iso_value),
        ).fetchall()
        return [Deal.from_row(r) for r in rows]


def try_lock(deal_id: int) -> bool:
    """Атомарно помечает сделку как 'в обработке'. Возвращает False, если она уже занята
    (защита от повторной обработки одной и той же строки шедулером/обработчиком входящих)."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE deals SET in_progress = 1, updated_at = ? WHERE deal_id = ? AND in_progress = 0",
            (now_iso(), deal_id),
        )
        return cur.rowcount > 0


def reschedule(deal_id: int, next_action_at: str) -> None:
    """Переносит next_action_at без смены статуса и снимает in_progress — используется для
    повторной попытки позже, если отправка упала с ошибкой."""
    with _connect() as conn:
        conn.execute(
            "UPDATE deals SET next_action_at = ?, in_progress = 0, updated_at = ? WHERE deal_id = ?",
            (next_action_at, now_iso(), deal_id),
        )


def unlock(deal_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE deals SET in_progress = 0, updated_at = ? WHERE deal_id = ?",
            (now_iso(), deal_id),
        )


def release_all_locks() -> list[int]:
    """Снимает все блокировки при старте main.py. Блокировка живёт в БД, и если процесс
    завершился, держа её (SIGTERM/сторож — os._exit, падение), сделка выпадала из работы навсегда:
    шедулер её не берёт, ответы клиента отбрасываются (сделки 39649375, 40064126, 40092103,
    40333975). На старте других владельцев быть не может — второй экземпляр не даёт запустить
    core/process_lock.py. Статус и next_action_at не меняются. Возвращает id разблокированных."""
    with _connect() as conn:
        ids = [row["deal_id"] for row in conn.execute("SELECT deal_id FROM deals WHERE in_progress = 1")]
        if ids:
            conn.execute("UPDATE deals SET in_progress = 0 WHERE in_progress = 1")
    return ids


def stop_reminders(deal_id: int) -> None:
    """Сделку вручную перевели в amoCRM на этап вне зоны ответственности бота (не «Первичные
    переговоры»/«Молчание»/«Уточнение ТЗ») — снимаем next_action_at, чтобы шедулер больше не
    подбирал эту сделку, статус в локальной БД не трогаем."""
    ts = now_iso()
    with _connect() as conn:
        conn.execute(
            "UPDATE deals SET next_action_at = NULL, in_progress = 0, updated_at = ? WHERE deal_id = ?",
            (ts, deal_id),
        )
    log_event(deal_id, "system", None, "Напоминания остановлены: сделка вручную перемещена на другой этап CRM")


def restart_reminder_cycle(deal_id: int, next_action_at: str) -> int:
    """Бот сам задал клиенту уточняющий вопрос (ответ из базы знаний + вопрос "передавать ли
    задачу на оценку партнёрам") и ждёт ответа — запускает ту же цепочку напоминаний, что и после
    первого сообщения (см. core/state_machine.py: handle_incoming_reply/process_scheduler_tick).
    Инкрементирует `faq_cycle_count` и возвращает новое значение — по нему вызывающая сторона
    решает, не пора ли принудительно эскалировать вместо очередного автоответа (защита от
    бесконечного цикла, см. P-020 в BACKLOG.md)."""
    ts = now_iso()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE deals
            SET status = ?, next_action_at = ?, reminder_count = 0,
                faq_cycle_count = faq_cycle_count + 1, in_progress = 0, updated_at = ?
            WHERE deal_id = ?
            """,
            (Status.AWAITING_REPLY_1.value, next_action_at, ts, deal_id),
        )
        row = conn.execute(
            "SELECT faq_cycle_count FROM deals WHERE deal_id = ?", (deal_id,)
        ).fetchone()
        return row["faq_cycle_count"]


def increment_faq_cycle_count(deal_id: int) -> int:
    """Как и `restart_reminder_cycle`, но БЕЗ побочных эффектов на status/next_action_at/
    in_progress — нужно узнать новое значение счётчика ДО решения, продолжать ли цикл
    (`resume_awaiting_reply`, снимает лок) или сразу эскалировать, не отпуская лок раньше времени
    (P-039 в BACKLOG.md: иначе конкурентный `handle_incoming_reply` может успеть `try_lock` и
    запустить дублирующий цикл, пока эскалация ещё не подтверждена)."""
    ts = now_iso()
    with _connect() as conn:
        conn.execute(
            "UPDATE deals SET faq_cycle_count = faq_cycle_count + 1, updated_at = ? WHERE deal_id = ?",
            (ts, deal_id),
        )
        row = conn.execute(
            "SELECT faq_cycle_count FROM deals WHERE deal_id = ?", (deal_id,)
        ).fetchone()
        return row["faq_cycle_count"]


def resume_awaiting_reply(deal_id: int, next_action_at: str) -> None:
    """Часть `restart_reminder_cycle` без инкремента `faq_cycle_count` (см.
    `increment_faq_cycle_count`) — используется, когда счётчик уже увеличен отдельно и решение
    "продолжаем цикл, не эскалируем" уже принято (P-039 в BACKLOG.md)."""
    ts = now_iso()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE deals
            SET status = ?, next_action_at = ?, reminder_count = 0, in_progress = 0, updated_at = ?
            WHERE deal_id = ?
            """,
            (Status.AWAITING_REPLY_1.value, next_action_at, ts, deal_id),
        )


# ---------------------------------------------------------------------------
# Telegram flood-wait cooldown
# ---------------------------------------------------------------------------

def set_telegram_cooldown(until_iso: str) -> None:
    """Глобальный cooldown на исходящие Telegram-сообщения (после FloodWait/PeerFlood)."""
    set_kv("telegram_cooldown_until", until_iso)


def get_telegram_cooldown() -> str | None:
    return get_kv("telegram_cooldown_until")


def set_kv(key: str, value: str) -> None:
    """Простое key-value хранилище для служебных данных (OAuth-токены amoCRM, cooldown'ы)."""
    with _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS kv_store (key TEXT PRIMARY KEY, value TEXT)"
        )
        conn.execute(
            "INSERT INTO kv_store(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_kv(key: str) -> str | None:
    with _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS kv_store (key TEXT PRIMARY KEY, value TEXT)"
        )
        row = conn.execute("SELECT value FROM kv_store WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


# ---------------------------------------------------------------------------
# Дневной лимит отправок в Telegram (anti-ban предохранитель)
# ---------------------------------------------------------------------------

def increment_and_check_daily_cap(cap: int) -> bool:
    """Инкрементирует счётчик отправок за текущий день (UTC-дата) и возвращает False,
    если дневной лимит уже превышен (отправку нужно пропустить и залогировать)."""
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
    """Текущее значение счётчика за сегодня БЕЗ инкремента — используется для проверки лимита
    ДО попытки отправки (см. telegram_channel/ratelimit.py: is_send_allowed, P-017 в
    BACKLOG.md), сам инкремент — отдельно, только по факту реальной попытки."""
    day = datetime.now(timezone.utc).date().isoformat()
    with _connect() as conn:
        row = conn.execute("SELECT count FROM send_counters WHERE day = ?", (day,)).fetchone()
        return row["count"] if row else 0


# ---------------------------------------------------------------------------
# Журнал сообщений
# ---------------------------------------------------------------------------

def log_event(deal_id: int, direction: str, channel: str | None, text: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO events_log (deal_id, ts, direction, channel, text) VALUES (?, ?, ?, ?, ?)",
            (deal_id, now_iso(), direction, channel, text),
        )


def get_last_event_ts(deal_id: int) -> str | None:
    """Время последнего события (входящего или исходящего) по сделке — граница, после которой
    сообщения клиента ещё не обработаны (telegram_channel/catch_up.py)."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT max(ts) FROM events_log WHERE deal_id = ?", (deal_id,)
        ).fetchone()
        return row[0] if row else None


def list_new_deals() -> list[Deal]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM deals WHERE status = ?", (Status.NEW.value,)).fetchall()
        return [Deal.from_row(r) for r in rows]


def get_first_outgoing_channel(deal_id: int) -> str | None:
    """Канал первого исходящего сообщения сделки, None — исходящих не было."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT channel FROM events_log WHERE deal_id = ? AND direction = 'out' ORDER BY id LIMIT 1",
            (deal_id,),
        ).fetchone()
    return row["channel"] if row else None


def has_outgoing_text(deal_id: int, text: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM events_log WHERE deal_id = ? AND direction = 'out' AND text = ? LIMIT 1",
            (deal_id, text),
        ).fetchone()
    return row is not None


def get_last_outgoing_text(deal_id: int) -> str | None:
    """Последнее сообщение бота клиенту — контекст для классификации ответа: голое "нет" на
    "Хотите что-то дополнить?" — согласие, а на "Заявка актуальна?" — отказ (сделка 40333785)."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT text FROM events_log WHERE deal_id = ? AND direction = 'out' ORDER BY id DESC LIMIT 1",
            (deal_id,),
        ).fetchone()
    return row["text"] if row else None


def list_recent_activity(since_iso: str) -> list[dict]:
    """Сделки, по которым было хоть одно событие начиная с `since_iso` — по каждой сделке только
    САМОЕ ПОЗДНЕЕ событие в окне. Используется периодическим отчётом в вебхук (см.
    reporting/reporter.py, P-014 в BACKLOG.md)."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT e.deal_id, e.ts, e.direction, e.text, d.channel, d.status
            FROM events_log e
            JOIN deals d ON d.deal_id = e.deal_id
            WHERE e.ts >= ?
            ORDER BY e.deal_id, e.ts
            """,
            (since_iso,),
        ).fetchall()
    latest: dict[int, sqlite3.Row] = {}
    for row in rows:
        latest[row["deal_id"]] = row  # ORDER BY ts ASC — последняя запись на deal_id и есть новейшая
    return [
        {
            "deal_id": row["deal_id"],
            "channel": row["channel"] or "",
            "status": row["status"],
            "direction": row["direction"],
            "text": row["text"] or "",
            "date": row["ts"],
        }
        for row in latest.values()
    ]
