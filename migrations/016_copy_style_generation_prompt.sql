-- Единая точка управления флоу «Сделать такую же»: промпт генерации (Gemini) только отсюда, не из «Промпт генерации»/трендов.
ALTER TABLE copy_style_settings ADD COLUMN IF NOT EXISTS generation_system_prompt_prefix TEXT NOT NULL DEFAULT '';
ALTER TABLE copy_style_settings ADD COLUMN IF NOT EXISTS generation_negative_prompt TEXT NOT NULL DEFAULT '';
ALTER TABLE copy_style_settings ADD COLUMN IF NOT EXISTS generation_safety_constraints TEXT NOT NULL DEFAULT 'no text generation, no chat.';
ALTER TABLE copy_style_settings ADD COLUMN IF NOT EXISTS generation_image_constraints_template TEXT NOT NULL DEFAULT 'size={size}, format={format}';
ALTER TABLE copy_style_settings ADD COLUMN IF NOT EXISTS generation_default_size VARCHAR(32) NOT NULL DEFAULT '1024x1024';
ALTER TABLE copy_style_settings ADD COLUMN IF NOT EXISTS generation_default_format VARCHAR(16) NOT NULL DEFAULT 'png';
ALTER TABLE copy_style_settings ADD COLUMN IF NOT EXISTS generation_default_model VARCHAR(128) NOT NULL DEFAULT '';
