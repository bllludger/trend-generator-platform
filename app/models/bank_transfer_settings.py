"""Настройки оплаты переводом на карту: реквизиты, промпты Vision, допуски, тексты бота."""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text

from app.db.base import Base


class BankTransferSettings(Base):
    """Одна строка (id=1). Управляется из админки «Оплата переводом»."""

    __tablename__ = "bank_transfer_settings"

    id = Column(Integer, primary_key=True, default=1)
    enabled = Column(Boolean, nullable=False, default=False)
    card_number = Column(String(32), nullable=False, default="")
    comment = Column(Text, nullable=False, default="")

    # Распознавание чека (Vision)
    receipt_system_prompt = Column(Text, nullable=False, default="")
    receipt_user_prompt = Column(Text, nullable=False, default="")
    receipt_vision_model = Column(String(64), nullable=False, default="gpt-4o")
    amount_tolerance_abs = Column(Float, nullable=False, default=1.0)
    amount_tolerance_pct = Column(Float, nullable=False, default=0.02)

    # Тексты в боте (шаг 1, шаг 2, успех, несовпадение суммы)
    step1_description = Column(Text, nullable=False, default="")
    step2_requisites = Column(Text, nullable=False, default="")
    success_message = Column(Text, nullable=False, default="")
    amount_mismatch_message = Column(Text, nullable=False, default="")

    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
