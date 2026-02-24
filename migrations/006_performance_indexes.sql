-- Performance indexes for admin/telemetry/audit queries (2026 stability)
-- Speeds up: WHERE created_at >= ?, ORDER BY created_at DESC

CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_user_created ON jobs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_actor_created ON audit_logs(actor_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action_created ON audit_logs(action, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_token_ledger_created_at ON token_ledger(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at DESC);
