"""
PackOrder — заказ на покупку пакета (Neo Start / Neo Pro / Neo Unlimited) по ссылке ЮKassa.
Точка истины для статуса оплаты и активации пакета; активация через process_session_purchase_yookassa_link.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, Integer, String

from app.db.base import Base


class PackOrder(Base):
    __tablename__ = "pack_orders"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    telegram_user_id = Column(String, nullable=False, index=True)
    pack_id = Column(String, nullable=False, index=True)
    amount_kopecks = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="created")
    yookassa_payment_id = Column(String, nullable=True, index=True)
    confirmation_url = Column(String, nullable=True)
    idempotence_key = Column(String, nullable=True)
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

    # status: created | payment_pending | paid | completed | canceled | failed
