-- 068: Audit as single event log — add user_id and session_id for telemetry/metrics queries
-- Enables funnel and metrics to be built from audit_logs without joining on actor_id.
-- Depends on: table users must exist (REFERENCES users(id)).

ALTER TABLE audit_logs
  ADD COLUMN IF NOT EXISTS user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS session_id TEXT;

CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id_created_at ON audit_logs(user_id, created_at DESC) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_audit_logs_session_id_created_at ON audit_logs(session_id, created_at DESC) WHERE session_id IS NOT NULL;
