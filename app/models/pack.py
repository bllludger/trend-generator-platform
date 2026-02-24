"""
Pack model — настраиваемые пакеты генераций для продажи за Telegram Stars.
Управляются из админки, порядок задаётся через order_index.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.db.base import Base


class Pack(Base):
    __tablename__ = "packs"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    name = Column(String, nullable=False)                    # "Starter"
    emoji = Column(String, nullable=False, default="")
    tokens = Column(Integer, nullable=False)                 # 5 / 15 / 50 генераций
    stars_price = Column(Integer, nullable=False)            # 25 / 65 / 175 Stars
    description = Column(String, nullable=False, default="")  # "5 фото без watermark"
    enabled = Column(Boolean, nullable=False, default=True)
    order_index = Column(Integer, nullable=False, default=0)
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
