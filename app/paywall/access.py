"""
Decision только: decide_access(ctx) -> AccessDecision.
Чистая функция, без I/O. Guardrails: subscription_active -> full, is_unlocked -> full.
Временная совместимость: reserved_tokens > 0 -> full (см. план миграции).
"""
from __future__ import annotations

import logging

from app.paywall.config import get_unlock_cost_stars, get_unlock_cost_tokens
from app.paywall.models import AccessContext, AccessDecision, UnlockOptions

logger = logging.getLogger(__name__)


def decide_access(ctx: AccessContext) -> AccessDecision:
    """
    Решает, показывать ли превью с watermark или полную версию.

    Guardrails (все ведут к full):
    - subscription_active -> полная версия
    - is_unlocked (unlocked_at/unlock_method) -> полная версия
    - reserved_tokens > 0 (временная совместимость) -> полная версия

    Превью показываем только если: нет guardrail и генерация «бесплатная»
    (used_free_quota или used_copy_quota) и оплата не зафиксирована.
    """
    # Guardrail: подписчик всегда full
    if ctx.subscription_active:
        return AccessDecision(
            show_preview=False,
            unlock_options=_default_unlock_options(),
        )

    # Guardrail: уже разблокировано (целевой источник истины)
    if ctx.is_unlocked:
        return AccessDecision(
            show_preview=False,
            unlock_options=_default_unlock_options(),
        )

    # Временная совместимость: reserved_tokens трактуем как «оплата за эту генерацию
    # зарезервирована» (источник истины — unlocked_at/unlock_method в Job).
    # МИГРАЦИЯ: после перехода всех сценариев на unlocked_at/unlock_method убрать
    # эту ветку и не передавать reserved_tokens в AccessContext.
    if ctx.reserved_tokens > 0:
        return AccessDecision(
            show_preview=False,
            unlock_options=_default_unlock_options(),
        )

    # Бесплатная генерация (free или copy квота) -> превью с watermark
    if ctx.used_free_quota or ctx.used_copy_quota:
        return AccessDecision(
            show_preview=True,
            unlock_options=_default_unlock_options(),
        )

    # Платная генерация (токены зарезервированы при создании job и т.д.) — уже обработано выше
    # Или генерация без квот — отдаём full (на всякий случай)
    return AccessDecision(
        show_preview=False,
        unlock_options=_default_unlock_options(),
    )


def _default_unlock_options() -> UnlockOptions:
    return UnlockOptions(
        show_tokens=True,
        show_stars=True,
        cost_tokens=get_unlock_cost_tokens(),
        cost_stars=get_unlock_cost_stars(),
    )
