"""Настройки сервиса «Сделать такую же»: модель ChatGPT, системный и пользовательский промпты (редактируются в админке)."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.db.base import Base


class CopyStyleSettings(Base):
    """Одна запись (id=1): модель и промпты для анализа референса в флоу «Сделать такую же»."""

    __tablename__ = "copy_style_settings"

    id = Column(Integer, primary_key=True, default=1)
    model = Column(String(128), nullable=False, default="gpt-4o")
    system_prompt = Column(Text, nullable=False, default="")
    user_prompt = Column(Text, nullable=False, default="")
    max_tokens = Column(Integer, nullable=False, default=1536)
    # Всегда добавляется к custom_prompt при отправке в Gemini: «всегда добавляй человека/людей с фото в сцену»
    prompt_suffix = Column(Text, nullable=False, default="")
    # Инструкции для Gemini при 3 фото (стиль + 2 лица) и 2 фото (2 лица) — редактируются в админке
    prompt_instruction_3_images = Column(Text, nullable=False, default="")
    prompt_instruction_2_images = Column(Text, nullable=False, default="")
    # Промпт генерации (Gemini) — только для флоу «Сделать такую же», не смешивается с трендами
    generation_system_prompt_prefix = Column(Text, nullable=False, default="")
    generation_negative_prompt = Column(Text, nullable=False, default="")
    generation_safety_constraints = Column(Text, nullable=False, default="no text generation, no chat.")
    generation_image_constraints_template = Column(Text, nullable=False, default="size={size}, format={format}")
    generation_default_size = Column(String(32), nullable=False, default="1024x1024")
    generation_default_format = Column(String(16), nullable=False, default="png")
    generation_default_model = Column(String(128), nullable=False, default="")
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
