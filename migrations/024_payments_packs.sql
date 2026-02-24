-- 024: Telegram Stars monetization — payments, packs, new user/job fields

-- Таблица пакетов генераций
CREATE TABLE IF NOT EXISTS packs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    emoji TEXT NOT NULL DEFAULT '',
    tokens INTEGER NOT NULL,
    stars_price INTEGER NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    order_index INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Таблица платежей (Telegram Stars)
CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    telegram_payment_charge_id TEXT UNIQUE NOT NULL,
    provider_payment_charge_id TEXT,
    pack_id TEXT NOT NULL,
    stars_amount INTEGER NOT NULL,
    tokens_granted INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'completed',
    payload TEXT NOT NULL,
    job_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    refunded_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id);
CREATE INDEX IF NOT EXISTS idx_payments_created_at ON payments(created_at);

-- Новые поля в users
ALTER TABLE users ADD COLUMN IF NOT EXISTS total_purchased INTEGER NOT NULL DEFAULT 0;

-- Новые поля в jobs
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS output_path_original TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS is_preview BOOLEAN NOT NULL DEFAULT FALSE;

-- Дефолтные пакеты (seed)
INSERT INTO packs (id, name, emoji, tokens, stars_price, description, enabled, order_index)
VALUES
    ('starter', 'Starter', '⭐', 5, 25, '5 фото без watermark', TRUE, 0),
    ('standard', 'Standard', '🌟', 15, 65, '15 фото без watermark (скидка 13%)', TRUE, 1),
    ('pro', 'Pro', '💎', 50, 175, '50 фото без watermark (скидка 30%)', TRUE, 2)
ON CONFLICT (id) DO NOTHING;
