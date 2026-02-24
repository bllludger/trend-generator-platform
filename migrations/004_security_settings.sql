-- Global security settings (single row)
CREATE TABLE IF NOT EXISTS security_settings (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    free_requests_per_day INTEGER NOT NULL DEFAULT 10,
    default_rate_limit_per_hour INTEGER NOT NULL DEFAULT 20,
    subscriber_rate_limit_per_hour INTEGER NOT NULL DEFAULT 100,
    new_user_first_day_limit INTEGER NOT NULL DEFAULT 5,
    max_failures_before_auto_suspend INTEGER NOT NULL DEFAULT 15,
    auto_suspend_hours INTEGER NOT NULL DEFAULT 24,
    cooldown_minutes_after_failures INTEGER NOT NULL DEFAULT 10,
    vip_bypass_rate_limit BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

INSERT INTO security_settings (
    id, free_requests_per_day, default_rate_limit_per_hour, subscriber_rate_limit_per_hour,
    new_user_first_day_limit, max_failures_before_auto_suspend, auto_suspend_hours,
    cooldown_minutes_after_failures, vip_bypass_rate_limit
) VALUES (
    1, 10, 20, 100, 5, 15, 24, 10, FALSE
) ON CONFLICT (id) DO NOTHING;

-- Job: used free daily quota (no token deduction)
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS used_free_daily_quota BOOLEAN NOT NULL DEFAULT FALSE;
