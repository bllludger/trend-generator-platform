-- Migration: Add security/moderation fields to users table
-- Date: 2026-01-31

-- Ban fields
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS ban_reason TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS banned_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS banned_by TEXT;

-- Suspend fields
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_suspended BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS suspended_until TIMESTAMP WITH TIME ZONE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS suspend_reason TEXT;

-- Rate limiting
ALTER TABLE users ADD COLUMN IF NOT EXISTS rate_limit_per_hour INTEGER;

-- Admin notes & flags
ALTER TABLE users ADD COLUMN IF NOT EXISTS admin_notes TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS flags JSONB NOT NULL DEFAULT '{}';

-- Indexes for filtering
CREATE INDEX IF NOT EXISTS idx_users_is_banned ON users(is_banned) WHERE is_banned = TRUE;
CREATE INDEX IF NOT EXISTS idx_users_is_suspended ON users(is_suspended) WHERE is_suspended = TRUE;
CREATE INDEX IF NOT EXISTS idx_users_rate_limit ON users(rate_limit_per_hour) WHERE rate_limit_per_hour IS NOT NULL;
