from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db.base import Base


class TrendPost(Base):
    """Публикация тренда в Telegram-канал (автопостер)."""

    __tablename__ = "trend_posts"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    trend_id = Column(String, ForeignKey("trends.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_id = Column(String, nullable=False)
    caption = Column(Text, nullable=True)
    telegram_message_id = Column(Integer, nullable=True)
    status = Column(String(32), nullable=False, default="draft")  # draft | sent | deleted
    sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    trend = relationship("Trend", backref="trend_posts", lazy="joined")
