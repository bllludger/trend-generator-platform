-- Add image_size_tier to generation_prompt_settings (Gemini-native imageConfig.imageSize)
ALTER TABLE generation_prompt_settings ADD COLUMN IF NOT EXISTS default_image_size_tier VARCHAR(8) NOT NULL DEFAULT '1K';
-- Add image_size_tier to app_settings for global override
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS default_image_size_tier VARCHAR(8) NOT NULL DEFAULT '1K';
-- Add default_aspect_ratio to generation_prompt_settings
ALTER TABLE generation_prompt_settings ADD COLUMN IF NOT EXISTS default_aspect_ratio VARCHAR(16) NOT NULL DEFAULT '1:1';
