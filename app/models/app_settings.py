from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.db.base import Base


class AppSettings(Base):
    """Global app settings (single row, id=1). Toggles, watermark and preview quality from admin."""

    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, default=1)
    use_nano_banana_pro = Column(Boolean, nullable=False, default=False)
    # Вотермарк: пусто = из .env WATERMARK_TEXT; иначе переопределение из админки
    watermark_text = Column(String(128), nullable=True)
    watermark_opacity = Column(Integer, nullable=False, default=60)  # 0–255
    watermark_tile_spacing = Column(Integer, nullable=False, default=200)
    # Превью 3 вариантов Take: макс. сторона после даунскейла перед вотермарком (меньше = хуже качество)
    take_preview_max_dim = Column(Integer, nullable=False, default=800)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
