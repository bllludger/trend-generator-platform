"""Настройки промпта генерации: мастер-текст (prompt_input), legacy-колонки task/identity/safety и дефолты модели."""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base


class GenerationPromptSettings(Base):
    """Две записи: id=1 (Превью), id=2 (Release). Мастер-текст + опциональные legacy-поля + дефолты модели."""

    __tablename__ = "generation_prompt_settings"

    id = Column(Integer, primary_key=True)  # 1 = preview, 2 = release
    prompt_input = Column(Text, nullable=False, default="")
    prompt_input_enabled = Column(Boolean, nullable=False, default=True)
    prompt_task = Column(Text, nullable=False, default="")  # не участвует в сборке промпта; см. migrations/077
    prompt_task_enabled = Column(Boolean, nullable=False, default=True)
    prompt_identity_transfer = Column(Text, nullable=False, default="")
    prompt_identity_transfer_enabled = Column(Boolean, nullable=False, default=True)
    safety_constraints = Column(Text, nullable=False, default="")
    safety_constraints_enabled = Column(Boolean, nullable=False, default=True)
    # Дефолты модели
    default_model = Column(String(128), nullable=False, default="gemini-2.5-flash-image")
    default_size = Column(String(32), nullable=False, default="1024x1024")
    default_format = Column(String(16), nullable=False, default="png")
    default_temperature = Column(Float, nullable=False, default=0.7)
    default_temperature_a = Column(Float, nullable=True)
    default_temperature_b = Column(Float, nullable=True)
    default_temperature_c = Column(Float, nullable=True)
    default_image_size_tier = Column(String(8), nullable=False, default="1K")
    default_aspect_ratio = Column(String(16), nullable=False, default="3:4")
    default_top_p = Column(Float, nullable=True)
    default_top_p_a = Column(Float, nullable=True)
    default_top_p_b = Column(Float, nullable=True)
    default_top_p_c = Column(Float, nullable=True)
    default_seed = Column(Integer, nullable=True)
    default_candidate_count = Column(Integer, nullable=False, default=1)
    default_media_resolution = Column(String(16), nullable=True)
    default_thinking_config = Column(JSONB, nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
