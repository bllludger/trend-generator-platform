"""Тесты admin API: _payment_method_from_row, payments/history."""
from datetime import date
from unittest.mock import MagicMock

import pytest


class TestPaymentMethodFromRow:
    """_payment_method_from_row классифицирует способ оплаты по записи Payment."""

    def test_bank_transfer(self):
        from app.api.routes.admin import _payment_method_from_row
        from app.models.payment import Payment

        p = MagicMock(spec=Payment)
        p.payload = "bank_transfer:ref-123"
        p.telegram_payment_charge_id = "anything"
        assert _payment_method_from_row(p) == "bank_transfer"

    def test_yoomoney(self):
        from app.api.routes.admin import _payment_method_from_row
        from app.models.payment import Payment

        p = MagicMock(spec=Payment)
        p.payload = "other"
        p.telegram_payment_charge_id = "yoomoney:provider-123"
        assert _payment_method_from_row(p) == "yoomoney"

    def test_yookassa_unlock(self):
        from app.api.routes.admin import _payment_method_from_row
        from app.models.payment import Payment

        p = MagicMock(spec=Payment)
        p.payload = "yookassa_unlock:pay-id"
        p.telegram_payment_charge_id = "yookassa_unlock:pay-id"
        assert _payment_method_from_row(p) == "yookassa_unlock"

    def test_yookassa_link(self):
        from app.api.routes.admin import _payment_method_from_row
        from app.models.payment import Payment

        p = MagicMock(spec=Payment)
        p.payload = "other"
        p.telegram_payment_charge_id = "yookassa_link:pay-456"
        assert _payment_method_from_row(p) == "yookassa_link"

    def test_stars_default(self):
        from app.api.routes.admin import _payment_method_from_row
        from app.models.payment import Payment

        p = MagicMock(spec=Payment)
        p.payload = "pack:starter:user:u1:nonce:x"
        p.telegram_payment_charge_id = "tg-charge-123"
        assert _payment_method_from_row(p) == "stars"


class TestPaymentsHistoryResponseStructure:
    """payments_history возвращает series с полями date, revenue_rub, transactions_count, unique_buyers, by_pack."""

    def test_returns_series_with_expected_keys(self):
        from app.api.routes.admin import payments_history

        mock_row = MagicMock()
        mock_row.dt = date(2026, 3, 1)
        mock_row.revenue_rub = 100.5
        mock_row.revenue_stars = 0
        mock_row.transactions_count = 2
        mock_row.unique_buyers = 1
        mock_pack = MagicMock()
        mock_pack.dt = date(2026, 3, 1)
        mock_pack.pack_id = "trial"
        mock_pack.cnt = 1
        mock_pack.revenue_rub = 100.5

        db = MagicMock()
        q = MagicMock()
        q.filter.return_value = q
        chain1 = MagicMock()
        chain1.group_by.return_value.order_by.return_value.all.return_value = [mock_row]
        chain2 = MagicMock()
        chain2.group_by.return_value.all.return_value = [mock_pack]
        q.with_entities.side_effect = [chain1, chain2]
        db.query.return_value.filter.return_value = q

        result = payments_history(
            db=db,
            date_from=date(2026, 3, 1),
            date_to=date(2026, 3, 1),
            granularity="day",
            pack_id=None,
        )
        assert "series" in result
        assert len(result["series"]) == 1
        point = result["series"][0]
        assert point["date"] == "2026-03-01"
        assert point["revenue_rub"] == 100.5
        assert point["transactions_count"] == 2
        assert point["unique_buyers"] == 1
        assert "by_pack" in point
        assert isinstance(point["by_pack"], list)
        assert len(point["by_pack"]) == 1
        assert point["by_pack"][0]["pack_id"] == "trial"
        assert point["by_pack"][0]["count"] == 1
        assert point["by_pack"][0]["revenue_rub"] == 100.5
