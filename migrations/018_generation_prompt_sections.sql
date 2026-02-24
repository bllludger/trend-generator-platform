-- Add structured prompt sections for generation prompt settings
ALTER TABLE generation_prompt_settings ADD COLUMN IF NOT EXISTS definitions TEXT NOT NULL DEFAULT '';
ALTER TABLE generation_prompt_settings ADD COLUMN IF NOT EXISTS definitions_enabled BOOLEAN NOT NULL DEFAULT true;

ALTER TABLE generation_prompt_settings ADD COLUMN IF NOT EXISTS priority_order TEXT NOT NULL DEFAULT '';
ALTER TABLE generation_prompt_settings ADD COLUMN IF NOT EXISTS priority_order_enabled BOOLEAN NOT NULL DEFAULT true;

ALTER TABLE generation_prompt_settings ADD COLUMN IF NOT EXISTS identity_rules TEXT NOT NULL DEFAULT '';
ALTER TABLE generation_prompt_settings ADD COLUMN IF NOT EXISTS identity_rules_enabled BOOLEAN NOT NULL DEFAULT true;

ALTER TABLE generation_prompt_settings ADD COLUMN IF NOT EXISTS negative_constraints TEXT NOT NULL DEFAULT '';
ALTER TABLE generation_prompt_settings ADD COLUMN IF NOT EXISTS negative_constraints_enabled BOOLEAN NOT NULL DEFAULT true;
