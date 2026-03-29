"""Tests for referral config: bonus ladder calculation (Neo plans: 153, 384, 762)."""
from unittest.mock import patch


def test_calc_bonus_credits_exact_threshold():
    with patch("app.referral.config.settings") as mock_settings:
        mock_settings.referral_bonus_ladder = '{"153": 2, "384": 4, "762": 8}'
        from app.referral.config import calc_bonus_credits

        assert calc_bonus_credits(153) == 2
        assert calc_bonus_credits(384) == 4
        assert calc_bonus_credits(762) == 8


def test_calc_bonus_credits_between_thresholds():
    with patch("app.referral.config.settings") as mock_settings:
        mock_settings.referral_bonus_ladder = '{"153": 2, "384": 4, "762": 8}'
        from app.referral.config import calc_bonus_credits

        assert calc_bonus_credits(300) == 2
        assert calc_bonus_credits(700) == 4


def test_calc_bonus_credits_below_threshold():
    with patch("app.referral.config.settings") as mock_settings:
        mock_settings.referral_bonus_ladder = '{"153": 2, "384": 4}'
        from app.referral.config import calc_bonus_credits

        assert calc_bonus_credits(100) == 0
        assert calc_bonus_credits(152) == 0
