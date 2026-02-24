CREATE TABLE IF NOT EXISTS telegram_message_templates (
    id SERIAL PRIMARY KEY,
    key VARCHAR(128) NOT NULL UNIQUE,
    value TEXT NOT NULL DEFAULT '',
    description TEXT NULL,
    category VARCHAR(64) NOT NULL DEFAULT 'general',
    updated_by VARCHAR(64) NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_telegram_message_templates_key ON telegram_message_templates(key);
CREATE INDEX IF NOT EXISTS idx_telegram_message_templates_category ON telegram_message_templates(category);
