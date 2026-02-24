-- Дополнительный промпт к сцене: всегда добавляется к custom_prompt при отправке в Gemini (админка)
ALTER TABLE copy_style_settings ADD COLUMN IF NOT EXISTS prompt_suffix TEXT NOT NULL DEFAULT '';

-- Дефолт: явно просим добавлять людей с входного фото в сцену
UPDATE copy_style_settings
SET prompt_suffix = 'Always include the person or people from the input image in this scene. Preserve their number, placement and roles. Do not remove or add subjects.'
WHERE id = 1 AND (prompt_suffix IS NULL OR prompt_suffix = '');
