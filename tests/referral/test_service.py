"""Tests for ReferralService — attribution, bonus lifecycle, limits, anti-fraud."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest


def _make_user(**kwargs):
    user = MagicMock()
    user.id = kwargs.get("id", str(uuid4()))
    user.telegram_id = kwargs.get("telegram_id", "123456")
    user.referral_code = kwargs.get("referral_code", None)
    user.referred_by_user_id = kwargs.get("referred_by_user_id", None)
    user.referred_at = kwargs.get("referred_at", None)
    user.hd_credits_balance = kwargs.get("hd_credits_balance", 0)
    user.hd_credits_pending = kwargs.get("hd_credits_pending", 0)
    user.hd_credits_debt = kwargs.get("hd_credits_debt", 0)
    user.has_purchased_hd = kwargs.get("has_purchased_hd", False)
    user.created_at = kwargs.get("created_at", datetime.now(timezone.utc))
    user.flags = kwargs.get("flags", {})
    return user


def _make_payment(**kwargs):
    p = MagicMock()
    p.id = kwargs.get("id", str(uuid4()))
    p.user_id = kwargs.get("user_id", str(uuid4()))
    p.stars_amount = kwargs.get("stars_amount", 249)
    p.pack_id = kwargs.get("pack_id", "premium")
    p.tokens_granted = kwargs.get("tokens_granted", 80)
    return p


class TestAttribution:
    def test_attribute_new_user(self):
        db = MagicMock()
        referrer = _make_user(referral_code="ABC12345")
        referral_user = _make_user(referred_by_user_id=None)
        db.query.return_value.filter.return_value.one_or_none.return_value = referrer

        from app.referral.service import ReferralService

        svc = ReferralService(db)
        with patch.object(svc, "get_referrer_by_code", return_value=referrer):
            result = svc.attribute(referral_user, "ABC12345")

        assert result is True
        assert referral_user.referred_by_user_id == referrer.id
        assert referral_user.referred_at is not None

    def test_attribute_already_attributed(self):
        db = MagicMock()
        referral_user = _make_user(referred_by_user_id="some_id")

        from app.referral.service import ReferralService

        svc = ReferralService(db)
        result = svc.attribute(referral_user, "ABC12345")
        assert result is False

    def test_attribute_self_referral(self):
        db = MagicMock()
        user = _make_user(id="USER1", referred_by_user_id=None)
        referrer = _make_user(id="USER1", referral_code="CODE1")

        from app.referral.service import ReferralService

        svc = ReferralService(db)
        with patch.object(svc, "get_referrer_by_code", return_value=referrer):
            result = svc.attribute(user, "CODE1")
        assert result is False

    def test_attribute_expired_window(self):
        db = MagicMock()
        old_date = datetime.now(timezone.utc) - timedelta(days=30)
        referral_user = _make_user(referred_by_user_id=None, created_at=old_date)
        referrer = _make_user(referral_code="CODE2")

        from app.referral.service import ReferralService

        svc = ReferralService(db)
        with patch.object(svc, "get_referrer_by_code", return_value=referrer):
            with patch("app.referral.service.get_attribution_window_days", return_value=7):
                result = svc.attribute(referral_user, "CODE2")
        assert result is False

    def test_attribute_code_not_found(self):
        db = MagicMock()
        referral_user = _make_user(referred_by_user_id=None)

        from app.referral.service import ReferralService

        svc = ReferralService(db)
        with patch.object(svc, "get_referrer_by_code", return_value=None):
            result = svc.attribute(referral_user, "NONEXIST")
        assert result is False


class TestCreateBonus:
    @patch("app.referral.service.get_min_pack_stars", return_value=249)
    @patch("app.referral.service.get_hold_hours", return_value=24)
    @patch("app.referral.service.calc_bonus_credits", return_value=2)
    def test_create_bonus_success(self, mock_calc, mock_hold, mock_min):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        referrer = _make_user()
        referral = _make_user()
        payment = _make_payment(stars_amount=249)

        from app.referral.service import ReferralService

        svc = ReferralService(db)
        with patch.object(svc, "_check_limits", return_value=True):
            with patch.object(svc, "check_anomaly", return_value=False):
                bonus = svc.create_bonus(referrer, referral, payment)

        assert bonus is not None
        assert bonus.hd_credits_amount == 2
        assert bonus.status == "pending"

    @patch("app.referral.service.get_min_pack_stars", return_value=249)
    def test_create_bonus_below_threshold(self, mock_min):
        db = MagicMock()
        referrer = _make_user()
        referral = _make_user()
        payment = _make_payment(stars_amount=100)

        from app.referral.service import ReferralService

        svc = ReferralService(db)
        bonus = svc.create_bonus(referrer, referral, payment)
        assert bonus is None

    @patch("app.referral.service.get_min_pack_stars", return_value=249)
    def test_create_bonus_unlock_excluded(self, mock_min):
        db = MagicMock()
        referrer = _make_user()
        referral = _make_user()
        payment = _make_payment(stars_amount=300, pack_id="unlock")

        from app.referral.service import ReferralService

        svc = ReferralService(db)
        bonus = svc.create_bonus(referrer, referral, payment)
        assert bonus is None

    @patch("app.referral.service.get_min_pack_stars", return_value=249)
    @patch("app.referral.service.get_hold_hours", return_value=24)
    @patch("app.referral.service.calc_bonus_credits", return_value=2)
    def test_create_bonus_limits_exceeded(self, mock_calc, mock_hold, mock_min):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        referrer = _make_user()
        referral = _make_user()
        payment = _make_payment(stars_amount=249)

        from app.referral.service import ReferralService

        svc = ReferralService(db)
        with patch.object(svc, "_check_limits", return_value=False):
            bonus = svc.create_bonus(referrer, referral, payment)
        assert bonus is None

    @patch("app.referral.service.get_min_pack_stars", return_value=249)
    @patch("app.referral.service.get_hold_hours", return_value=24)
    @patch("app.referral.service.calc_bonus_credits", return_value=4)
    def test_create_bonus_anomaly_flagged(self, mock_calc, mock_hold, mock_min):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        referrer = _make_user()
        referral = _make_user()
        payment = _make_payment(stars_amount=499)

        from app.referral.service import ReferralService

        svc = ReferralService(db)
        with patch.object(svc, "_check_limits", return_value=True):
            with patch.object(svc, "check_anomaly", return_value=True):
                bonus = svc.create_bonus(referrer, referral, payment)
        assert bonus is None


class TestSpendCredits:
    def test_spend_success(self):
        db = MagicMock()
        user = _make_user(hd_credits_balance=5, hd_credits_debt=0)
        locked_user = _make_user(hd_credits_balance=5, hd_credits_debt=0)
        db.query.return_value.filter.return_value.with_for_update.return_value.one.return_value = locked_user

        from app.referral.service import ReferralService

        svc = ReferralService(db)
        result = svc.spend_credits(user, 1)
        assert result is True
        assert locked_user.hd_credits_balance == 4

    def test_spend_blocked_by_debt(self):
        db = MagicMock()
        user = _make_user(hd_credits_balance=5, hd_credits_debt=2)

        from app.referral.service import ReferralService

        svc = ReferralService(db)
        result = svc.spend_credits(user, 1)
        assert result is False

    def test_spend_insufficient_balance(self):
        db = MagicMock()
        user = _make_user(hd_credits_balance=0, hd_credits_debt=0)
        locked_user = _make_user(hd_credits_balance=0)
        db.query.return_value.filter.return_value.with_for_update.return_value.one.return_value = locked_user

        from app.referral.service import ReferralService

        svc = ReferralService(db)
        result = svc.spend_credits(user, 1)
        assert result is False


class TestRevokeBonus:
    def test_revoke_pending(self):
        db = MagicMock()
        bonus = MagicMock()
        bonus.id = "B1"
        bonus.status = "pending"
        bonus.hd_credits_amount = 2
        bonus.referrer_user_id = "R1"
        db.query.return_value.filter.return_value.one_or_none.side_effect = [bonus, _make_user(id="R1", hd_credits_pending=2)]

        from app.referral.service import ReferralService

        svc = ReferralService(db)
        result = svc.revoke_bonus_by_payment("P1")
        assert result is True
        assert bonus.status == "revoked"

    def test_revoke_already_revoked(self):
        db = MagicMock()
        bonus = MagicMock()
        bonus.status = "revoked"
        db.query.return_value.filter.return_value.one_or_none.return_value = bonus

        from app.referral.service import ReferralService

        svc = ReferralService(db)
        result = svc.revoke_bonus_by_payment("P1")
        assert result is False

    def test_revoke_not_found(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.one_or_none.return_value = None

        from app.referral.service import ReferralService

        svc = ReferralService(db)
        result = svc.revoke_bonus_by_payment("P_NONEXIST")
        assert result is False


class TestCodeGeneration:
    def test_get_or_create_code_existing(self):
        db = MagicMock()
        user = _make_user(referral_code="EXISTING1")

        from app.referral.service import ReferralService

        svc = ReferralService(db)
        code = svc.get_or_create_code(user)
        assert code == "EXISTING1"

    def test_get_or_create_code_new(self):
        db = MagicMock()
        user = _make_user(referral_code=None)
        db.query.return_value.filter.return_value.first.return_value = None

        from app.referral.service import ReferralService

        svc = ReferralService(db)
        code = svc.get_or_create_code(user)
        assert code is not None
        assert len(code) >= 6


class TestBotParsing:
    def test_parse_referral_code(self):
        import sys
        sys.modules.pop("app.bot.main", None)
        from app.bot.main import _parse_referral_code

        assert _parse_referral_code("/start ref_ABC123") == "ABC123"
        assert _parse_referral_code("/start trend_xyz") is None
        assert _parse_referral_code("/start") is None
        assert _parse_referral_code(None) is None

    def test_parse_start_arg_still_works(self):
        from app.bot.main import _parse_start_arg

        assert _parse_start_arg("/start trend_abc") == "abc"
        assert _parse_start_arg("/start ref_xyz") is None
        assert _parse_start_arg("/start") is None
