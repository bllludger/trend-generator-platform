-- Параметры вотермарка и превью (3 варианта Take) в админке. Пусто = использовать .env/дефолты.
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS watermark_text VARCHAR(128) DEFAULT NULL;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS watermark_opacity INTEGER NOT NULL DEFAULT 60;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS watermark_tile_spacing INTEGER NOT NULL DEFAULT 200;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS take_preview_max_dim INTEGER NOT NULL DEFAULT 800;
