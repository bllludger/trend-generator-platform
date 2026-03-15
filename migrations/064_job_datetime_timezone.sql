-- Job: приведение колонок дат к TIMESTAMPTZ для единообразия (naive/aware в Python).
-- Меняем только если в БД колонка без time zone (idempotent).
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'jobs' AND column_name = 'created_at'
    AND data_type = 'timestamp without time zone'
  ) THEN
    ALTER TABLE jobs ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC';
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'jobs' AND column_name = 'updated_at'
    AND data_type = 'timestamp without time zone'
  ) THEN
    ALTER TABLE jobs ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at AT TIME ZONE 'UTC';
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'jobs' AND column_name = 'unlocked_at'
    AND data_type = 'timestamp without time zone'
  ) THEN
    ALTER TABLE jobs ALTER COLUMN unlocked_at TYPE TIMESTAMPTZ USING unlocked_at AT TIME ZONE 'UTC';
  END IF;
END $$;
