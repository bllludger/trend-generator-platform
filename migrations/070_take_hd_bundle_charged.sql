-- 070: One 4K charge per whole take (A/B/C), not per variant.

ALTER TABLE takes
ADD COLUMN IF NOT EXISTS hd_bundle_charged BOOLEAN NOT NULL DEFAULT FALSE;

-- Backfill: if any variant for take was already delivered in 4K, treat bundle as charged.
UPDATE takes t
SET hd_bundle_charged = TRUE
WHERE EXISTS (
    SELECT 1
    FROM favorites f
    WHERE f.take_id = t.id
      AND f.hd_status = 'delivered'
);
