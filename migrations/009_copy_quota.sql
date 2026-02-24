-- «Сделать такую же»: 1 бесплатная генерация на аккаунт (отдельно от основных 3)
ALTER TABLE users ADD COLUMN IF NOT EXISTS copy_generations_used INTEGER NOT NULL DEFAULT 0;

ALTER TABLE security_settings ADD COLUMN IF NOT EXISTS copy_generations_per_user INTEGER NOT NULL DEFAULT 1;

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS used_copy_quota BOOLEAN NOT NULL DEFAULT FALSE;
