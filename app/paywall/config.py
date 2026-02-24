"""
Paywall config — типизированная обёртка над app.core.config для watermark и цен unlock.
"""
from __future__ import annotations

from app.core.config import settings


def get_watermark_text() -> str:
    return getattr(settings, "watermark_text", "NanoBanan Preview")


def get_unlock_cost_tokens() -> int:
    return getattr(settings, "unlock_cost_tokens", 1)


def get_unlock_cost_stars() -> int:
    return getattr(settings, "unlock_cost_stars", 2)
