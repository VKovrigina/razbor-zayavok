CREATE TABLE IF NOT EXISTS calls (
    lead_id             INTEGER PRIMARY KEY,
    contact_id          INTEGER,
    contact_name        TEXT,
    telegram_username   TEXT,
    telegram_peer_id    INTEGER,
    status              TEXT NOT NULL,
    offered_slot_1      TEXT,
    offered_slot_2      TEXT,
    confirmed_slot      TEXT,
    calendar_event_uid  TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_calls_status ON calls(status);

CREATE TABLE IF NOT EXISTS kv_store (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- свой дневной антиспам-счётчик Telegram, не общий с main.py/main_cases.py
CREATE TABLE IF NOT EXISTS send_counters (
    day   TEXT PRIMARY KEY,
    count INTEGER NOT NULL DEFAULT 0
);
