-- Add amount_kopecks column to payments for YooMoney/RUB reconciliation
ALTER TABLE payments ADD COLUMN IF NOT EXISTS amount_kopecks INTEGER;
