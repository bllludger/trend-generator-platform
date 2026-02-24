from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.db.base import Base


class Trend(Base):
    __tablename__ = "trends"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    theme_id = Column(String, ForeignKey("themes.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String, nullable=False)
    emoji = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    system_prompt = Column(Text, nullable=False)
    scene_prompt = Column(Text, nullable=True)
    subject_prompt = Column(Text, nullable=True)  # legacy, не используется в новом PromptBuilder
    negative_prompt = Column(Text, nullable=False, default="")  # legacy, в новом builder — negative_scene
    negative_scene = Column(Text, nullable=True)  # что избегать в сцене (только визуальный стиль)
    subject_mode = Column(String(32), nullable=True, default="face")  # face | head_torso | full_body
    framing_hint = Column(String(32), nullable=True, default="portrait")  # close_up | portrait | half_body | full_body
    style_preset = Column(JSONB, nullable=False, default=dict)
    max_images = Column(Integer, nullable=False, default=1)
    enabled = Column(Boolean, nullable=False, default=True)
    order_index = Column(Integer, nullable=False, default=0)
    example_image_path = Column(String, nullable=True)  # путь к примеру результата (показ в боте и админке)
    style_reference_image_path = Column(String, nullable=True)  # референс стиля для Gemini (IMAGE_2), копировать освещение/композицию
    # Playground 1:1: когда заданы — воркер собирает промпт из секций вместо build_final_prompt_payload
    prompt_sections = Column(JSONB, nullable=True)  # list of {id, type, label, content, enabled, order}
    prompt_model = Column(String(128), nullable=True)
    prompt_size = Column(String(32), nullable=True)
    prompt_format = Column(String(16), nullable=True)
    # Playground profile: Gemini-native + reproducibility (1:1 в тренд)
    prompt_aspect_ratio = Column(String(16), nullable=True, default="1:1")
    prompt_image_size_tier = Column(String(8), nullable=True, default="1K")
    prompt_temperature = Column(Float, nullable=True)  # 0.0 .. 2.0
    prompt_seed = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    theme = relationship("Theme", backref="trends", lazy="joined")
