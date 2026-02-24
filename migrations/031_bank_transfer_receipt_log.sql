-- Лог каждой попытки распознавания чека (оплата переводом): сырой ответ Vision, регулярка, извлечённая сумма, путь к файлу, пользователь.
CREATE TABLE IF NOT EXISTS bank_transfer_receipt_log (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    telegram_user_id TEXT NOT NULL,
    user_id TEXT REFERENCES users(id),
    file_path TEXT NOT NULL,
    raw_vision_response TEXT NOT NULL DEFAULT '',
    regex_pattern TEXT NOT NULL DEFAULT '',
    extracted_amount_rub NUMERIC,
    expected_rub NUMERIC NOT NULL,
    match_success BOOLEAN NOT NULL,
    pack_id TEXT NOT NULL,
    payment_id TEXT,
    error_message TEXT,
    vision_model VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_bank_transfer_receipt_log_created_at ON bank_transfer_receipt_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bank_transfer_receipt_log_telegram_user_id ON bank_transfer_receipt_log(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_bank_transfer_receipt_log_match_success ON bank_transfer_receipt_log(match_success);
