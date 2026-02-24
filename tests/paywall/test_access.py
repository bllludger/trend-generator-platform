"""
Unit-тесты для decide_access: чистая логика, без файлов/PIL.
"""
import unittest
from unittest.mock import patch

from app.paywall.access import decide_access
from app.paywall.models import AccessContext, UnlockOptions


class TestDecideAccess(unittest.TestCase):
    """Тесты guardrails и правил превью."""

    @patch("app.paywall.access.get_unlock_cost_tokens", return_value=1)
    @patch("app.paywall.access.get_unlock_cost_stars", return_value=2)
    def test_subscription_active_always_full(self, *_):
        ctx = AccessContext(
            user_id="u1",
            subscription_active=True,
            used_free_quota=True,
            used_copy_quota=False,
            is_unlocked=False,
            reserved_tokens=0,
        )
        decision = decide_access(ctx)
        self.assertFalse(decision.show_preview)

    @patch("app.paywall.access.get_unlock_cost_tokens", return_value=1)
    @patch("app.paywall.access.get_unlock_cost_stars", return_value=2)
    def test_is_unlocked_always_full(self, *_):
        ctx = AccessContext(
            user_id="u1",
            subscription_active=False,
            used_free_quota=True,
            used_copy_quota=False,
            is_unlocked=True,
            reserved_tokens=0,
        )
        decision = decide_access(ctx)
        self.assertFalse(decision.show_preview)

    @patch("app.paywall.access.get_unlock_cost_tokens", return_value=1)
    @patch("app.paywall.access.get_unlock_cost_stars", return_value=2)
    def test_reserved_tokens_positive_full(self, *_):
        """Временная совместимость: reserved_tokens > 0 -> full."""
        ctx = AccessContext(
            user_id="u1",
            subscription_active=False,
            used_free_quota=True,
            used_copy_quota=False,
            is_unlocked=False,
            reserved_tokens=1,
        )
        decision = decide_access(ctx)
        self.assertFalse(decision.show_preview)

    @patch("app.paywall.access.get_unlock_cost_tokens", return_value=1)
    @patch("app.paywall.access.get_unlock_cost_stars", return_value=2)
    def test_free_quota_show_preview(self, *_):
        ctx = AccessContext(
            user_id="u1",
            subscription_active=False,
            used_free_quota=True,
            used_copy_quota=False,
            is_unlocked=False,
            reserved_tokens=0,
        )
        decision = decide_access(ctx)
        self.assertTrue(decision.show_preview)

    @patch("app.paywall.access.get_unlock_cost_tokens", return_value=1)
    @patch("app.paywall.access.get_unlock_cost_stars", return_value=2)
    def test_copy_quota_show_preview(self, *_):
        ctx = AccessContext(
            user_id="u1",
            subscription_active=False,
            used_free_quota=False,
            used_copy_quota=True,
            is_unlocked=False,
            reserved_tokens=0,
        )
        decision = decide_access(ctx)
        self.assertTrue(decision.show_preview)

    @patch("app.paywall.access.get_unlock_cost_tokens", return_value=1)
    @patch("app.paywall.access.get_unlock_cost_stars", return_value=2)
    def test_no_quota_no_reserve_full(self, *_):
        """Ни free, ни copy квота, reserved_tokens=0 -> full (не превью)."""
        ctx = AccessContext(
            user_id="u1",
            subscription_active=False,
            used_free_quota=False,
            used_copy_quota=False,
            is_unlocked=False,
            reserved_tokens=0,
        )
        decision = decide_access(ctx)
        self.assertFalse(decision.show_preview)

    @patch("app.paywall.access.get_unlock_cost_tokens", return_value=1)
    @patch("app.paywall.access.get_unlock_cost_stars", return_value=2)
    def test_unlock_options_present(self, *_):
        ctx = AccessContext(
            user_id="u1",
            subscription_active=False,
            used_free_quota=True,
            used_copy_quota=False,
            is_unlocked=False,
            reserved_tokens=0,
        )
        decision = decide_access(ctx)
        self.assertIsInstance(decision.unlock_options, UnlockOptions)
        self.assertEqual(decision.unlock_options.cost_tokens, 1)
        self.assertEqual(decision.unlock_options.cost_stars, 2)
