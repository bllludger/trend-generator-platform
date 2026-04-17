-- Generation prompt: только 4 блока [INPUT], [TASK], [IDENTITY TRANSFER], [SAFETY]
-- Добавляем новые колонки; старые (system_prompt_prefix, definitions, ...) не трогаем — приложение их больше не читает.

ALTER TABLE generation_prompt_settings ADD COLUMN IF NOT EXISTS prompt_input TEXT NOT NULL DEFAULT '';
ALTER TABLE generation_prompt_settings ADD COLUMN IF NOT EXISTS prompt_input_enabled BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE generation_prompt_settings ADD COLUMN IF NOT EXISTS prompt_task TEXT NOT NULL DEFAULT '';
ALTER TABLE generation_prompt_settings ADD COLUMN IF NOT EXISTS prompt_task_enabled BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE generation_prompt_settings ADD COLUMN IF NOT EXISTS prompt_identity_transfer TEXT NOT NULL DEFAULT '';
ALTER TABLE generation_prompt_settings ADD COLUMN IF NOT EXISTS prompt_identity_transfer_enabled BOOLEAN NOT NULL DEFAULT true;

-- Мастер-промпт (prompt_input / prompt_task) не заполняем шаблоном — только в админке.
-- Подсказка для переноса лица, если колонка ещё пустая.
UPDATE generation_prompt_settings
SET
  prompt_identity_transfer = 'Preserve the face and identity from the user photo. Do not alter facial features, skin tone, or distinguishing characteristics.'
WHERE id = 1
  AND (prompt_identity_transfer = '' OR prompt_identity_transfer IS NULL);
