"""Настройки промпта генерации: только блоки [INPUT], [TASK], [IDENTITY TRANSFER], [SAFETY] и дефолты модели."""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text

from app.db.base import Base


class GenerationPromptSettings(Base):
    """Одна запись (id=1): 4 блока промпта + дефолты модели."""

    __tablename__ = "generation_prompt_settings"

    id = Column(Integer, primary_key=True, default=1)
    # Блоки [INPUT], [TASK], [IDENTITY TRANSFER], [SAFETY]
    prompt_input = Column(Text, nullable=False, default="")
    prompt_input_enabled = Column(Boolean, nullable=False, default=True)
    prompt_task = Column(Text, nullable=False, default="")
    prompt_task_enabled = Column(Boolean, nullable=False, default=True)
    prompt_identity_transfer = Column(Text, nullable=False, default="")
    prompt_identity_transfer_enabled = Column(Boolean, nullable=False, default=True)
    safety_constraints = Column(Text, nullable=False, default="no text generation, no chat.")
    safety_constraints_enabled = Column(Boolean, nullable=False, default=True)
    # Дефолты модели
    default_model = Column(String(128), nullable=False, default="gemini-2.5-flash-image")
    default_size = Column(String(32), nullable=False, default="1024x1024")
    default_format = Column(String(16), nullable=False, default="png")
    default_temperature = Column(Float, nullable=False, default=0.7)
    default_image_size_tier = Column(String(8), nullable=False, default="1K")
    default_aspect_ratio = Column(String(16), nullable=False, default="1:1")
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
