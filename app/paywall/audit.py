"""
Аудит разблокировок: record_unlock вызывается только из бота по факту успешного unlock.
"""
from __future__ import annotations

import logging
from typing import Literal

logger = logging.getLogger(__name__)

UnlockMethod = Literal["tokens", "stars"]


def record_unlock(
    job_id: str,
    user_id: str,
    method: UnlockMethod,
    *,
    price_stars: int = 0,
    price_tokens: int = 0,
    pack_id: str | None = None,
    receipt_id: str | None = None,
    preview_to_pay_latency_seconds: float | None = None,
) -> None:
    """
    Записать событие успешной разблокировки для аналитики.
    Вызывать только после того как оригинал отправлен или платёж подтверждён.
    """
    logger.info(
        "paywall_unlock",
        extra={
            "job_id": job_id,
            "user_id": user_id,
            "method": method,
            "price_stars": price_stars,
            "price_tokens": price_tokens,
            "pack_id": pack_id,
            "receipt_id": receipt_id,
            "preview_to_pay_latency_seconds": preview_to_pay_latency_seconds,
        },
    )
