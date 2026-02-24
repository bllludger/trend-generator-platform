-- 038: Referral program — user fields + referral_bonuses table

-- Поля реферальной программы в users
ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code VARCHAR UNIQUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by_user_id VARCHAR REFERENCES users(id);
ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS hd_credits_balance INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS hd_credits_pending INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS hd_credits_debt INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS has_purchased_hd BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_users_referral_code ON users(referral_code);
CREATE INDEX IF NOT EXISTS idx_users_referred_by ON users(referred_by_user_id);

-- Таблица бонусов реферальной программы
CREATE TABLE IF NOT EXISTS referral_bonuses (
    id TEXT PRIMARY KEY,
    referrer_user_id TEXT NOT NULL REFERENCES users(id),
    referral_user_id TEXT NOT NULL REFERENCES users(id),
    payment_id TEXT NOT NULL REFERENCES payments(id),
    pack_stars INTEGER NOT NULL,
    hd_credits_amount INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    available_at TIMESTAMPTZ NOT NULL,
    spent_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    revoke_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_rb_referrer_status ON referral_bonuses(referrer_user_id, status);
CREATE INDEX IF NOT EXISTS idx_rb_referral ON referral_bonuses(referral_user_id);
CREATE INDEX IF NOT EXISTS idx_rb_status_available ON referral_bonuses(status, available_at);
CREATE INDEX IF NOT EXISTS idx_rb_payment ON referral_bonuses(payment_id);
