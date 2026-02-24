"""
Payment model — хранение всех транзакций Telegram Stars.
telegram_payment_charge_id уникален и используется для рефандов.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, Integer, String

from app.db.base import Base


class Payment(Base):
    __tablename__ = "payments"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, nullable=False, index=True)
    telegram_payment_charge_id = Column(String, unique=True, nullable=False)
    provider_payment_charge_id = Column(String, nullable=True)
    pack_id = Column(String, nullable=False)                 # "starter" / "standard" / "pro" / "unlock"
    stars_amount = Column(Integer, nullable=False)            # сколько Stars заплатил
    tokens_granted = Column(Integer, nullable=False)          # сколько генераций начислено
    status = Column(String, nullable=False, default="completed")  # completed / refunded
    payload = Column(String, nullable=False)                  # верификационный payload
    job_id = Column(String, nullable=True)                    # для unlock — ссылка на разблокируемый job
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    refunded_at = Column(DateTime(timezone=True), nullable=True)
