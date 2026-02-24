-- Тренд: референс стиля для Gemini (IMAGE_2). Отдельно от example_image_path (пример результата для показа в боте).
ALTER TABLE trends ADD COLUMN IF NOT EXISTS style_reference_image_path TEXT NULL;
