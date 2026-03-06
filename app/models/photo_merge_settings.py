from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.db.base import Base


class PhotoMergeSettings(Base):
    """Настройки сервиса склейки фото (singleton, id=1)."""

    __tablename__ = "photo_merge_settings"

    id = Column(Integer, primary_key=True, default=1)
    # Форматы выходного файла: png | jpeg
    output_format = Column(String(16), nullable=False, default="png")
    # Качество JPEG (1-95, игнорируется при output_format=png)
    jpeg_quality = Column(Integer, nullable=False, default=92)
    # Максимальная ширина/высота результата (0 = без ограничения)
    max_output_side_px = Column(Integer, nullable=False, default=0)
    # Максимальный размер входного файла в МБ
    max_input_file_mb = Column(Integer, nullable=False, default=20)
    # Фоновый цвет при компоновке (hex, например "#ffffff")
    background_color = Column(String(16), nullable=False, default="#ffffff")
    # Включить/выключить сервис
    enabled = Column(Boolean, nullable=False, default=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
