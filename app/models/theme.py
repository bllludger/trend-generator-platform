from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base


class Theme(Base):
    """Тематика трендов. target_audiences — в каких ЦА показывать: women, men, couples."""

    __tablename__ = "themes"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    name = Column(String, nullable=False)
    emoji = Column(String, nullable=False, default="")
    order_index = Column(Integer, nullable=False, default=0)
    enabled = Column(Boolean, nullable=False, default=True)
    target_audiences = Column(JSONB, nullable=False, default=lambda: ["women"])  # ["women"] | ["men"] | ["couples"] | комбинации
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
