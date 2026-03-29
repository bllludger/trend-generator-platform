-- 071: Trial V2 + Referral Unlock + Trial bundle checkout (all 3)

-- Users: eligibility and "first successful preview completed" marker
ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_v2_eligible BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_first_preview_completed BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_first_preview_completed_at TIMESTAMPTZ;

-- Progress per user
CREATE TABLE IF NOT EXISTS trial_v2_progress (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL UNIQUE REFERENCES users(id),
    trend_slots_used INTEGER NOT NULL DEFAULT 0,
    rerolls_used INTEGER NOT NULL DEFAULT 0,
    takes_used INTEGER NOT NULL DEFAULT 0,
    reward_earned_total INTEGER NOT NULL DEFAULT 0,
    reward_claimed_total INTEGER NOT NULL DEFAULT 0,
    reward_available INTEGER NOT NULL DEFAULT 0,
    reward_reserved INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trial_v2_progress_user_id
    ON trial_v2_progress (user_id);

-- Trial trend slots (max 3 unique trends per user, 1 reroll each)
CREATE TABLE IF NOT EXISTS trial_v2_trend_slots (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    trend_id TEXT NOT NULL,
    takes_count INTEGER NOT NULL DEFAULT 0,
    reroll_used BOOLEAN NOT NULL DEFAULT FALSE,
    last_take_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trial_v2_slots_user_id
    ON trial_v2_trend_slots (user_id);
CREATE INDEX IF NOT EXISTS idx_trial_v2_slots_trend_id
    ON trial_v2_trend_slots (trend_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_trial_v2_slots_user_trend
    ON trial_v2_trend_slots (user_id, trend_id);

-- Persistent queue of selected previews for reward claim
CREATE TABLE IF NOT EXISTS trial_v2_selections (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    take_id TEXT NOT NULL REFERENCES takes(id),
    variant TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    source TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    claimed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_trial_v2_selections_user_status_created
    ON trial_v2_selections (user_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_trial_v2_selections_take_id
    ON trial_v2_selections (take_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_trial_v2_selection_pending
    ON trial_v2_selections (user_id, take_id, variant)
    WHERE status = 'pending';

-- Reward events from referral-first-preview condition
CREATE TABLE IF NOT EXISTS referral_trial_rewards (
    id TEXT PRIMARY KEY,
    referrer_user_id TEXT NOT NULL REFERENCES users(id),
    referral_user_id TEXT NOT NULL REFERENCES users(id),
    reason TEXT NOT NULL DEFAULT 'first_preview',
    rewarded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ref_trial_rewards_referrer
    ON referral_trial_rewards (referrer_user_id);
CREATE INDEX IF NOT EXISTS idx_ref_trial_rewards_referral
    ON referral_trial_rewards (referral_user_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ref_trial_rewards_referrer_referral
    ON referral_trial_rewards (referrer_user_id, referral_user_id);

-- Bundle order for "unlock all 3" (299 ₽)
CREATE TABLE IF NOT EXISTS trial_bundle_orders (
    id TEXT PRIMARY KEY,
    telegram_user_id TEXT NOT NULL,
    take_id TEXT NOT NULL REFERENCES takes(id),
    variants JSONB NOT NULL DEFAULT '[]'::jsonb,
    amount_kopecks INTEGER NOT NULL DEFAULT 29900,
    status TEXT NOT NULL DEFAULT 'created',
    yookassa_payment_id TEXT,
    confirmation_url TEXT,
    idempotence_key TEXT,
    delivered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trial_bundle_orders_tg_take
    ON trial_bundle_orders (telegram_user_id, take_id);
CREATE INDEX IF NOT EXISTS idx_trial_bundle_orders_status
    ON trial_bundle_orders (status);
CREATE INDEX IF NOT EXISTS idx_trial_bundle_orders_payment_id
    ON trial_bundle_orders (yookassa_payment_id) WHERE yookassa_payment_id IS NOT NULL;
