-- Small operational values a daemon keeps across restarts, one row per key.
-- The Telegram host stores the next update offset here so a restart does not
-- replay messages it has already handled.
CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
