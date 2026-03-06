"""Настройки автопостера трендов: шаблон подписи (channel_id из config)."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, Text

from app.db.base import Base


class PosterSettings(Base):
    """Одна запись (id=1): канал, шаблон подписи и текст инлайн-кнопки. Плейсхолдеры: {name}, {emoji}, {description}, {theme}, {theme_emoji}."""

    __tablename__ = "poster_settings"

    id = Column(Integer, primary_key=True, default=1)
    poster_channel_id = Column(Text, nullable=True)  # @username или -100...; приоритет над env POSTER_CHANNEL_ID
    poster_bot_username = Column(Text, nullable=True)  # без @; для диплинка; приоритет над env TELEGRAM_BOT_USERNAME
    poster_default_template = Column(Text, nullable=False, default="")
    poster_button_text = Column(Text, nullable=False, default="Попробовать")
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
