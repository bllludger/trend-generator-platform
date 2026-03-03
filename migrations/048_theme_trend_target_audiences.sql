-- Целевая аудитория (ЦА): women, men, couples. По умолчанию только women.
-- Идемпотентность: добавляем колонку только если её ещё нет.

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'themes' AND column_name = 'target_audiences'
  ) THEN
    ALTER TABLE themes ADD COLUMN target_audiences JSONB NOT NULL DEFAULT '["women"]';
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'trends' AND column_name = 'target_audiences'
  ) THEN
    ALTER TABLE trends ADD COLUMN target_audiences JSONB NOT NULL DEFAULT '["women"]';
  END IF;
END $$;

-- Backfill на случай старых строк (если колонка была добавлена без DEFAULT в другой среде)
UPDATE themes SET target_audiences = '["women"]' WHERE target_audiences IS NULL;
UPDATE trends SET target_audiences = '["women"]' WHERE target_audiences IS NULL;
