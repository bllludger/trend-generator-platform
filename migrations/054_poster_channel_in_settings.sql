-- Migration 054: канал автопостера можно задать в настройках (БД), не только в env

ALTER TABLE poster_settings
ADD COLUMN IF NOT EXISTS poster_channel_id TEXT;

COMMENT ON COLUMN poster_settings.poster_channel_id IS 'Канал Telegram для автопостера (@username или -100...). Если задан — используется вместо POSTER_CHANNEL_ID из env.';
