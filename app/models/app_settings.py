from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer

from app.db.base import Base


class AppSettings(Base):
    """Global app settings (single row, id=1). Toggles and overrides from admin."""

    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, default=1)
    use_nano_banana_pro = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
