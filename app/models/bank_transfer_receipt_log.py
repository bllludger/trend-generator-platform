"""Лог попыток распознавания чека при оплате переводом на карту."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Numeric, String, Text

from app.db.base import Base


class BankTransferReceiptLog(Base):
    """Одна запись = одна попытка распознавания чека (Vision + regex)."""

    __tablename__ = "bank_transfer_receipt_log"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    telegram_user_id = Column(String, nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    file_path = Column(Text, nullable=False)
    raw_vision_response = Column(Text, nullable=False, default="")
    regex_pattern = Column(Text, nullable=False, default="")
    extracted_amount_rub = Column(Numeric(12, 2), nullable=True)
    expected_rub = Column(Numeric(12, 2), nullable=False)
    match_success = Column(Boolean, nullable=False)
    pack_id = Column(String, nullable=False)
    payment_id = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    vision_model = Column(String(64), nullable=True)

    # --- Проверка карты ---
    card_match_success = Column(Boolean, nullable=True)
    extracted_card_first4 = Column(String(4), nullable=True)
    extracted_card_last4 = Column(String(4), nullable=True)

    # --- Безопасность ---
    receipt_fingerprint = Column(Text, nullable=True)          # SHA-256 отпечаток чека
    extracted_receipt_dt = Column(DateTime(timezone=True), nullable=True)  # дата/время перевода с чека
    extracted_comment = Column(Text, nullable=True)            # комментарий, извлечённый Vision
    comment_match_success = Column(Boolean, nullable=True)     # совпал ли комментарий с ожидаемым
    rejection_reason = Column(Text, nullable=True)             # причина отклонения (duplicate_receipt, receipt_too_old, ...)
