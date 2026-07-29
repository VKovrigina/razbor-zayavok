CREATE TABLE IF NOT EXISTS deals (
    deal_id             INTEGER PRIMARY KEY,
    contact_id          INTEGER,
    status              TEXT NOT NULL,
    channel             TEXT,
    telegram_username   TEXT,
    telegram_peer_id    INTEGER,
    email_address       TEXT,
    contact_name        TEXT,
    stack_text          TEXT,
    case_text           TEXT,
    reminder_count      INTEGER NOT NULL DEFAULT 0,
    faq_cycle_count     INTEGER NOT NULL DEFAULT 0,
    messaging_tariff_flagged INTEGER NOT NULL DEFAULT 0,
    next_action_at      TEXT,
    in_progress         INTEGER NOT NULL DEFAULT 0,
    telegram_send_cooldown_until TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_deals_peer ON deals(telegram_peer_id);
CREATE INDEX IF NOT EXISTS idx_deals_email ON deals(email_address);
CREATE INDEX IF NOT EXISTS idx_deals_status ON deals(status);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    access_token  TEXT,
    refresh_token TEXT,
    expires_at    TEXT,
    updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS events_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id   INTEGER,
    ts        TEXT NOT NULL,
    direction TEXT NOT NULL,
    channel   TEXT,
    text      TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_deal ON events_log(deal_id);

-- защита от повторного создания дневного счётчика отправок при рестарте
CREATE TABLE IF NOT EXISTS send_counters (
    day   TEXT PRIMARY KEY,
    count INTEGER NOT NULL DEFAULT 0
);
