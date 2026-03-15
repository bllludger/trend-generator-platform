"""Регрессионные тесты PaymentService: unlock guards, rate limit fail closed."""
from unittest.mock import MagicMock, patch

import pytest


class TestHasUnlockPaymentForJob:
    """has_unlock_payment_for_job — защита от повторной оплаты за один job."""

    def test_returns_true_when_completed_unlock_payment_exists(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.limit.return_value.first.return_value = "any"

        from app.services.payments.service import PaymentService

        svc = PaymentService(db)
        assert svc.has_unlock_payment_for_job("job-123") is True
        db.query.return_value.filter.return_value.limit.assert_called_once_with(1)

    def test_returns_false_when_no_unlock_payment(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.limit.return_value.first.return_value = None

        from app.services.payments.service import PaymentService

        svc = PaymentService(db)
        assert svc.has_unlock_payment_for_job("job-456") is False


class TestValidatePreCheckoutUnlockAlreadyPaid:
    """validate_pre_checkout для unlock отклоняет, если job уже оплачен или разблокирован."""

    def test_rejects_when_job_has_unlock_payment(self):
        db = MagicMock()
        user = MagicMock()
        user.id = "user-1"
        user.telegram_id = "tg-1"
        user.is_access_blocked.return_value = False
        job = MagicMock()
        job.job_id = "job-1"
        job.user_id = "user-1"
        job.unlocked_at = None

        from app.services.payments.service import PaymentService

        svc = PaymentService(db)
        db.query.return_value.filter.return_value.one_or_none.side_effect = [user, job]

        with patch.object(svc, "has_unlock_payment_for_job", return_value=True):
            with patch.object(svc, "_check_rate_limit", return_value=True):
                ok, msg = svc.validate_pre_checkout(
                    payload="pack:unlock:user:user-1:nonce:abc:job:job-1",
                    telegram_user_id="tg-1",
                    total_amount=2,
                    currency="XTR",
                )
        assert ok is False
        assert "разблокировано" in msg or "уже" in msg

    def test_rejects_when_job_unlocked_at_set(self):
        db = MagicMock()
        user = MagicMock()
        user.id = "user-1"
        user.telegram_id = "tg-1"
        user.is_access_blocked.return_value = False
        job = MagicMock()
        job.job_id = "job-1"
        job.user_id = "user-1"
        job.unlocked_at = "2025-01-01T12:00:00Z"  # уже разблокирован

        from app.services.payments.service import PaymentService

        svc = PaymentService(db)
        db.query.return_value.filter.return_value.one_or_none.side_effect = [user, job]

        with patch.object(svc, "has_unlock_payment_for_job", return_value=False):
            with patch.object(svc, "_check_rate_limit", return_value=True):
                ok, msg = svc.validate_pre_checkout(
                    payload="pack:unlock:user:user-1:nonce:abc:job:job-1",
                    telegram_user_id="tg-1",
                    total_amount=2,
                    currency="XTR",
                )
        assert ok is False
        assert "разблокировано" in msg or "уже" in msg


class TestRateLimitFailClosed:
    """При RedisError rate limit отклоняет покупку (fail closed)."""

    def test_returns_false_on_redis_error(self):
        db = MagicMock()
        import redis

        from app.services.payments.service import PaymentService

        svc = PaymentService(db)
        with patch.object(svc._redis, "incr", side_effect=redis.RedisError("connection refused")):
            result = svc._check_rate_limit("123456")
        assert result is False


class TestRecordYookassaUnlockPayment:
    """record_yookassa_unlock_payment — централизация: запись unlock по ЮKassa в payments."""

    def test_returns_none_when_order_has_no_yookassa_payment_id(self):
        from app.models.unlock_order import UnlockOrder
        from app.services.payments.service import PaymentService

        db = MagicMock()
        order = MagicMock(spec=UnlockOrder)
        order.yookassa_payment_id = None
        order.telegram_user_id = "123"
        order.amount_kopecks = 12900
        order.take_id = "take-1"
        order.id = "ord-1"
        svc = PaymentService(db)
        assert svc.record_yookassa_unlock_payment(order) is None

    def test_returns_none_when_user_not_found(self):
        from app.models.unlock_order import UnlockOrder
        from app.services.payments.service import PaymentService

        db = MagicMock()
        order = MagicMock(spec=UnlockOrder)
        order.yookassa_payment_id = "pay-abc"
        order.telegram_user_id = "999"
        order.amount_kopecks = 12900
        order.take_id = "take-1"
        order.id = "ord-1"
        db.query.return_value.filter.return_value.one_or_none.side_effect = [None]
        svc = PaymentService(db)
        assert svc.record_yookassa_unlock_payment(order) is None

    def test_creates_payment_and_returns_it_when_user_exists(self):
        from app.models.unlock_order import UnlockOrder
        from app.services.payments.service import PaymentService

        db = MagicMock()
        user = MagicMock()
        user.id = "user-1"
        user.telegram_id = "123"
        order = MagicMock(spec=UnlockOrder)
        order.yookassa_payment_id = "pay-xyz"
        order.telegram_user_id = "123"
        order.amount_kopecks = 12900
        order.take_id = "take-1"
        order.id = "ord-1"
        db.query.return_value.filter.return_value.one_or_none.side_effect = [None, user]
        db.add = MagicMock()
        db.flush = MagicMock()

        svc = PaymentService(db)
        result = svc.record_yookassa_unlock_payment(order)
        assert result is not None
        assert result.telegram_payment_charge_id == "yookassa_unlock:pay-xyz"
        assert result.pack_id == "unlock"
        assert result.amount_kopecks == 12900
        assert result.user_id == "user-1"
        db.add.assert_called_once()

    def test_idempotent_returns_existing_payment(self):
        from app.models.payment import Payment
        from app.models.unlock_order import UnlockOrder
        from app.services.payments.service import PaymentService

        db = MagicMock()
        existing = MagicMock(spec=Payment)
        existing.id = "existing-pay"
        order = MagicMock(spec=UnlockOrder)
        order.yookassa_payment_id = "pay-dup"
        order.telegram_user_id = "123"
        order.amount_kopecks = 12900
        order.take_id = "take-1"
        order.id = "ord-1"
        db.query.return_value.filter.return_value.one_or_none.return_value = existing
        svc = PaymentService(db)
        result = svc.record_yookassa_unlock_payment(order)
        assert result is existing
        db.add.assert_not_called()
