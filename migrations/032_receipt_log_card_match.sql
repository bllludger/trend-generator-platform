-- Добавить поля проверки карты в лог чеков.
ALTER TABLE bank_transfer_receipt_log ADD COLUMN IF NOT EXISTS card_match_success BOOLEAN;
ALTER TABLE bank_transfer_receipt_log ADD COLUMN IF NOT EXISTS extracted_card_first4 VARCHAR(4);
ALTER TABLE bank_transfer_receipt_log ADD COLUMN IF NOT EXISTS extracted_card_last4 VARCHAR(4);
-- Поля для безопасности: отпечаток чека, извлечённая дата/время, комментарий, флаг дубликата.
ALTER TABLE bank_transfer_receipt_log ADD COLUMN IF NOT EXISTS receipt_fingerprint TEXT;
ALTER TABLE bank_transfer_receipt_log ADD COLUMN IF NOT EXISTS extracted_receipt_dt TIMESTAMP WITH TIME ZONE;
ALTER TABLE bank_transfer_receipt_log ADD COLUMN IF NOT EXISTS extracted_comment TEXT;
ALTER TABLE bank_transfer_receipt_log ADD COLUMN IF NOT EXISTS comment_match_success BOOLEAN;
ALTER TABLE bank_transfer_receipt_log ADD COLUMN IF NOT EXISTS rejection_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_btrl_receipt_fingerprint ON bank_transfer_receipt_log(receipt_fingerprint) WHERE receipt_fingerprint IS NOT NULL;
