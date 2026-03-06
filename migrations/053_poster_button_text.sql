-- Migration 053: текст инлайн-кнопки в poster_settings (кнопка с диплинком под постом)

ALTER TABLE poster_settings
ADD COLUMN IF NOT EXISTS poster_button_text TEXT NOT NULL DEFAULT 'Попробовать';

COMMENT ON COLUMN poster_settings.poster_button_text IS 'Текст инлайн-кнопки под постом; ссылка ведёт на диплинк тренда.';
