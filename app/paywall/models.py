"""
DTO paywall: AccessContext (вход decide_access), AccessDecision, DeliveryResult, UnlockOptions.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


# ----- Вход для decide_access (единый контракт, чтобы не расползаться по сигнатурам) -----


class AccessContext(BaseModel):
    """Единый контракт входа для decide_access: user_id, subscription_active, флаги job."""

    user_id: str
    subscription_active: bool = False
    # Флаги job
    used_free_quota: bool = False
    used_copy_quota: bool = False
    # Целевой источник истины оплаты/разблокировки (unlocked_at, unlock_method в Job).
    is_unlocked: bool = False  # True если job.unlocked_at не null
    # Временная совместимость: reserved_tokens > 0 -> full. После миграции убрать
    # из AccessContext и из логики decide_access (см. app/paywall/access.py).
    reserved_tokens: int = 0

    model_config = {"frozen": True}


# ----- Опции кнопок разблокировки (тупой слой keyboard только собирает разметку) -----


class UnlockOptions(BaseModel):
    """Флаги/опции для кнопок: какие показывать, цены. Без i18n/A/B логики."""

    show_tokens: bool = True
    show_stars: bool = True
    cost_tokens: int = 1
    cost_stars: int = 2

    model_config = {"frozen": True}


# ----- Решение доступа (чистая логика, без I/O) -----


class AccessDecision(BaseModel):
    """Результат decide_access: показывать ли превью с watermark и опции кнопок unlock."""

    show_preview: bool = Field(
        ...,
        description="True = отдавать превью с watermark и показывать кнопки разблокировки",
    )
    unlock_options: UnlockOptions = Field(
        ...,
        description="Опции для кнопок (при show_preview=True используются в keyboard)",
    )

    model_config = {"frozen": True}


# ----- Результат prepare_delivery (paths + flags для воркера) -----


class DeliveryResult(BaseModel):
    """Результат prepare_delivery: пути к файлам и флаги для воркера."""

    preview_path: str | None = Field(
        None,
        description="Путь к превью с watermark; None если отдаём только original",
    )
    original_path: str = Field(..., description="Путь к оригиналу без watermark")
    is_preview: bool = Field(
        ...,
        description="True = пользователю отдавать preview_path и показывать кнопки unlock",
    )
    unlock_options: UnlockOptions = Field(
        ...,
        description="Опции для reply_markup при is_preview",
    )

    model_config = {"frozen": True}
