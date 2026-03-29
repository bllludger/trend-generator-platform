"""
TrialBundleOrder — заказ на разблокировку всех 3 вариантов take по спец-цене Trial (129 ₽).
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base


class TrialBundleOrder(Base):
    __tablename__ = "trial_bundle_orders"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    telegram_user_id = Column(String, nullable=False, index=True)
    take_id = Column(String, nullable=False, index=True)
    variants = Column(JSONB, nullable=False, default=list)
    amount_kopecks = Column(Integer, nullable=False, default=12900)
    status = Column(String, nullable=False, default="created")
    yookassa_payment_id = Column(String, nullable=True, index=True)
    confirmation_url = Column(String, nullable=True)
    idempotence_key = Column(String, nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # status: created | payment_pending | paid | delivered | canceled | failed | delivery_failed

