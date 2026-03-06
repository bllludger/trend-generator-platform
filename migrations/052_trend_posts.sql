-- Migration 052: trend_posts (трекинг публикаций трендов в канал) и poster_settings (шаблон подписи)

CREATE TABLE IF NOT EXISTS trend_posts (
    id                   TEXT         NOT NULL PRIMARY KEY,
    trend_id             TEXT         NOT NULL REFERENCES trends(id) ON DELETE CASCADE,
    channel_id           TEXT         NOT NULL,
    caption              TEXT,
    telegram_message_id  INTEGER,
    status                TEXT         NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'sent', 'deleted')),
    sent_at              TIMESTAMPTZ,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_trend_posts_trend_id ON trend_posts (trend_id);
CREATE INDEX IF NOT EXISTS ix_trend_posts_status ON trend_posts (status);
CREATE INDEX IF NOT EXISTS ix_trend_posts_sent_at ON trend_posts (sent_at DESC);

CREATE TABLE IF NOT EXISTS poster_settings (
    id                      INTEGER     NOT NULL PRIMARY KEY DEFAULT 1,
    poster_default_template TEXT        NOT NULL DEFAULT $${emoji} {name}

{description}

Попробовать тут:$$,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO poster_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
