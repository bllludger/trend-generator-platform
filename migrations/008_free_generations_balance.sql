-- 1 аккаунт = 3 бесплатных генерации (жёсткий лимит, анти-абьюз)
ALTER TABLE users ADD COLUMN IF NOT EXISTS free_generations_used INTEGER NOT NULL DEFAULT 0;

-- Настройка в security_settings (по умолчанию 3)
ALTER TABLE security_settings ADD COLUMN IF NOT EXISTS free_generations_per_user INTEGER NOT NULL DEFAULT 3;
