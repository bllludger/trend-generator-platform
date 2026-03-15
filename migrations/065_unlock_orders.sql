-- Unlock orders: заказы на разблокировку одного фото по ссылке ЮKassa (вариант A/B/C).
-- Один активный payment_pending на связку (telegram_user_id, take_id, variant).
CREATE TABLE IF NOT EXISTS unlock_orders (
    id VARCHAR PRIMARY KEY,
    telegram_user_id VARCHAR NOT NULL,
    take_id VARCHAR NOT NULL,
    variant VARCHAR(1) NOT NULL,
    amount_kopecks INTEGER NOT NULL DEFAULT 12900,
    status VARCHAR NOT NULL DEFAULT 'created',
    yookassa_payment_id VARCHAR,
    confirmation_url VARCHAR,
    idempotence_key VARCHAR,
    delivered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);

CREATE INDEX IF NOT EXISTS idx_unlock_orders_telegram_take_variant
    ON unlock_orders (telegram_user_id, take_id, variant);
CREATE INDEX IF NOT EXISTS idx_unlock_orders_yookassa_payment_id
    ON unlock_orders (yookassa_payment_id) WHERE yookassa_payment_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_unlock_orders_status
    ON unlock_orders (status);

COMMENT ON TABLE unlock_orders IS 'Заказы разблокировки одного фото по ЮKassa (A/B/C). Статусы: created, payment_pending, paid, delivered, canceled, failed, delivery_failed.';
COMMENT ON COLUMN unlock_orders.idempotence_key IS 'Ключ идемпотентности для одной попытки создания платежа (UUID или order:order_id:attempt:attempt_id).';
