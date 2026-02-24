-- Пример результата для тренда: показывается в боте после выбора и в админке
ALTER TABLE trends ADD COLUMN IF NOT EXISTS example_image_path TEXT NULL;
