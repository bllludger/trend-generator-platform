-- Generation prompt: только 4 блока [INPUT], [TASK], [IDENTITY TRANSFER], [SAFETY]
-- Добавляем новые колонки; старые (system_prompt_prefix, definitions, ...) не трогаем — приложение их больше не читает.

ALTER TABLE generation_prompt_settings ADD COLUMN IF NOT EXISTS prompt_input TEXT NOT NULL DEFAULT '';
ALTER TABLE generation_prompt_settings ADD COLUMN IF NOT EXISTS prompt_input_enabled BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE generation_prompt_settings ADD COLUMN IF NOT EXISTS prompt_task TEXT NOT NULL DEFAULT '';
ALTER TABLE generation_prompt_settings ADD COLUMN IF NOT EXISTS prompt_task_enabled BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE generation_prompt_settings ADD COLUMN IF NOT EXISTS prompt_identity_transfer TEXT NOT NULL DEFAULT '';
ALTER TABLE generation_prompt_settings ADD COLUMN IF NOT EXISTS prompt_identity_transfer_enabled BOOLEAN NOT NULL DEFAULT true;

-- Заполнить рекомендуемыми значениями для существующей строки (id=1)
UPDATE generation_prompt_settings
SET
  prompt_input = 'IMAGE_1 = trend reference (scene/style). IMAGE_2 = user photo (preserve this identity in output).',
  prompt_task = 'Generate a single image: apply the scene and style from the trend to the subject from the user photo.',
  prompt_identity_transfer = 'Preserve the face and identity from the user photo. Do not alter facial features, skin tone, or distinguishing characteristics.'
WHERE id = 1 AND (prompt_input = '' OR prompt_input IS NULL);
