"""
Referral program config — typed wrappers over app.core.config.settings.
"""
from __future__ import annotations

import json

from app.core.config import settings


def get_min_pack_stars() -> int:
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
    """Return {min_stars: hd_credits} sorted descending by stars."""
    raw = json.loads(settings.referral_bonus_ladder)
    return {int(k): int(v) for k, v in raw.items()}


def calc_bonus_credits(pack_stars: int) -> int:
    """Determine HD credits for a given pack price using the bonus ladder."""
    ladder = get_bonus_ladder()
    result = 0
    for threshold in sorted(ladder.keys()):
        if pack_stars >= threshold:
            result = ladder[threshold]
    return result
