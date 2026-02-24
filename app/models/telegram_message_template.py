from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.db.base import Base


class TelegramMessageTemplate(Base):
    __tablename__ = "telegram_message_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(128), nullable=False, unique=True, index=True)
    value = Column(Text, nullable=False, default="")
    description = Column(Text, nullable=True)
    category = Column(String(64), nullable=False, default="general")
    updated_by = Column(String(64), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
