-- Custom prompt (for "Своя идея") and image format/size selection
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS custom_prompt TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS image_size VARCHAR(32);
