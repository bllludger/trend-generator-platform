-- Themes: thematic groups for trends (e.g. "23 февраля", "14 февраля")
CREATE TABLE IF NOT EXISTS themes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    emoji TEXT NOT NULL DEFAULT '',
    order_index INTEGER NOT NULL DEFAULT 0,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Link trends to theme; NULL = "Без тематики"
ALTER TABLE trends ADD COLUMN IF NOT EXISTS theme_id TEXT REFERENCES themes(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_trends_theme_id ON trends(theme_id);
