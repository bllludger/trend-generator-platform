from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer

from app.db.base import Base


class SecuritySettings(Base):
    """Global security settings (single row, id=1)."""

    __tablename__ = "security_settings"

    id = Column(Integer, primary_key=True, default=1)
    free_requests_per_day = Column(Integer, nullable=False, default=10)
    free_generations_per_user = Column(Integer, nullable=False, default=3)  # 1 account = 3 free
    copy_generations_per_user = Column(Integer, nullable=False, default=1)  # «Сделать такую же»: 1 free
    default_rate_limit_per_hour = Column(Integer, nullable=False, default=20)
    subscriber_rate_limit_per_hour = Column(Integer, nullable=False, default=100)
    new_user_first_day_limit = Column(Integer, nullable=False, default=5)
    max_failures_before_auto_suspend = Column(Integer, nullable=False, default=15)
    auto_suspend_hours = Column(Integer, nullable=False, default=24)
    cooldown_minutes_after_failures = Column(Integer, nullable=False, default=10)
    vip_bypass_rate_limit = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
