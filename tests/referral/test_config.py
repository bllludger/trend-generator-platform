"""Tests for referral config: bonus ladder calculation."""
from unittest.mock import patch


def test_calc_bonus_credits_exact_threshold():
    with patch("app.referral.config.settings") as mock_settings:
        mock_settings.referral_bonus_ladder = '{"249": 2, "499": 4, "999": 8}'
        from app.referral.config import calc_bonus_credits

        assert calc_bonus_credits(249) == 2
        assert calc_bonus_credits(499) == 4
        assert calc_bonus_credits(999) == 8


def test_calc_bonus_credits_between_thresholds():
    with patch("app.referral.config.settings") as mock_settings:
        mock_settings.referral_bonus_ladder = '{"249": 2, "499": 4, "999": 8}'
        from app.referral.config import calc_bonus_credits

        assert calc_bonus_credits(300) == 2
        assert calc_bonus_credits(600) == 4


def test_calc_bonus_credits_below_threshold():
    with patch("app.referral.config.settings") as mock_settings:
        mock_settings.referral_bonus_ladder = '{"249": 2, "499": 4}'
        from app.referral.config import calc_bonus_credits

        assert calc_bonus_credits(100) == 0
        assert calc_bonus_credits(248) == 0
