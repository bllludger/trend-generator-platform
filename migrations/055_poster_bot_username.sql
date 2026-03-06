-- Migration 055: username бота для диплинка в постах (кнопка «Попробовать» и ссылка в подписи)

ALTER TABLE poster_settings
ADD COLUMN IF NOT EXISTS poster_bot_username TEXT;

COMMENT ON COLUMN poster_settings.poster_bot_username IS 'Username бота без @ для диплинка (https://t.me/BOT?start=trend_ID). Если задан — используется вместо TELEGRAM_BOT_USERNAME из env.';
