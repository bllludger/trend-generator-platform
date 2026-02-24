-- Модератор: пользователь без лимитов (free/copy/токены/rate limit)
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_moderator BOOLEAN NOT NULL DEFAULT false;
