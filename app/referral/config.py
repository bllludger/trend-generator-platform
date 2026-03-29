"""
Referral program config — typed wrappers over app.core.config.settings.
"""
from __future__ import annotations

import json

from app.core.config import settings


def get_min_pack_stars() -> int:
    """Minimum pack price in Stars for referral bonus (Neo Start = 153)."""
    return settings.referral_min_pack_stars


def get_hold_hours() -> int:
    return settings.referral_hold_hours


def get_attribution_window_days() -> int:
    return settings.referral_attribution_window_days


def get_daily_limit() -> int:
    return settings.referral_daily_limit


def get_monthly_limit() -> int:
    return settings.referral_monthly_limit


def get_bonus_ladder() -> dict[int, int]:
    """Return {min_stars: credits_4k}. Thresholds align with Neo plans: 153 (Neo Start), 384 (Neo Pro), 762 (Neo Unlimited)."""
    raw = json.loads(settings.referral_bonus_ladder)
    return {int(k): int(v) for k, v in raw.items()}


def calc_bonus_credits(pack_stars: int) -> int:
    """Credits (4K) for the referrer from the bonus ladder by pack price in Stars (Neo plan tiers)."""
    ladder = get_bonus_ladder()
    result = 0
    for threshold in sorted(ladder.keys()):
        if pack_stars >= threshold:
            result = ladder[threshold]
    return result
