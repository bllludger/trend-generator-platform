-- Playground profile 1:1 in trend: aspect_ratio, image_size_tier, temperature, seed
ALTER TABLE trends ADD COLUMN IF NOT EXISTS prompt_aspect_ratio VARCHAR(16) DEFAULT '1:1';
ALTER TABLE trends ADD COLUMN IF NOT EXISTS prompt_image_size_tier VARCHAR(8) DEFAULT '1K';
ALTER TABLE trends ADD COLUMN IF NOT EXISTS prompt_temperature DOUBLE PRECISION DEFAULT 0.7;
ALTER TABLE trends ADD COLUMN IF NOT EXISTS prompt_seed INTEGER DEFAULT NULL;
