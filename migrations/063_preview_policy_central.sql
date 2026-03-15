-- Централизация политики превью: формат, качество, макс. сторона Job, двухслойный вотермарк.
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS preview_format VARCHAR(10) NOT NULL DEFAULT 'webp';
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS preview_quality INTEGER NOT NULL DEFAULT 85;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS job_preview_max_dim INTEGER NOT NULL DEFAULT 800;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS watermark_use_contrast BOOLEAN NOT NULL DEFAULT TRUE;
