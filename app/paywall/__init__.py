"""
Централизованный сервис paywall и watermark (внутренняя библиотека).
Decision (access) и execution (delivery) разделены; контракт через AccessContext.
"""
from app.paywall.access import decide_access
from app.paywall.audit import record_unlock
from app.paywall.delivery import prepare_delivery
from app.paywall.keyboard import build_unlock_markup
from app.paywall.models import (
    AccessContext,
    AccessDecision,
    DeliveryResult,
    UnlockOptions,
)

__all__ = [
    "AccessContext",
    "AccessDecision",
    "DeliveryResult",
    "UnlockOptions",
    "decide_access",
    "prepare_delivery",
    "build_unlock_markup",
    "record_unlock",
]
