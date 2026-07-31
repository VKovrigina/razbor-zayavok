CREATE TABLE IF NOT EXISTS cases (
    task_id                INTEGER PRIMARY KEY,
    deal_id                INTEGER NOT NULL,
    status                 TEXT NOT NULL,
    claimed_by_tg_user_id  INTEGER,
    claimed_by_tg_username TEXT,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cases_deal_id ON cases(deal_id);
CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);
