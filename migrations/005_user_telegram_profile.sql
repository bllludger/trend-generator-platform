-- User profile from Telegram (nickname, name)
ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_username VARCHAR(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_first_name VARCHAR(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_last_name VARCHAR(255);
