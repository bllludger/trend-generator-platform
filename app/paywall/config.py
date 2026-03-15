"""
Paywall config — типизированная обёртка над app.core.config для watermark и цен unlock.
"""
from __future__ import annotations

from app.core.config import settings


def get_watermark_text() -> str:
    return getattr(settings, "watermark_text", "@ai_nanobananastudio_bot")


def get_unlock_cost_tokens() -> int:
    return getattr(settings, "unlock_cost_tokens", 1)


def get_unlock_cost_stars() -> int:
    return getattr(settings, "unlock_cost_stars", 2)


# Разблокировка одного фото по ссылке ЮKassa — фиксированная цена в рублях
UNLOCK_PRICE_RUB = 129
UNLOCK_AMOUNT_KOPECKS = 12900  # 129 * 100


def get_unlock_amount_yookassa_value() -> str:
    """Сумма для API ЮKassa: строка в рублях, например '129.00'."""
    return f"{UNLOCK_PRICE_RUB}.00"


def get_unlock_amount_kopecks() -> int:
    """Сумма в копейках для хранения в БД."""
    return UNLOCK_AMOUNT_KOPECKS
