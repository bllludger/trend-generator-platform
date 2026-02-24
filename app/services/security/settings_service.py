from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.security_settings import SecuritySettings

# Validation limits for security settings
FREE_REQUESTS_RANGE = (0, 100)
RATE_LIMIT_RANGE = (1, 10000)
NEW_USER_LIMIT_RANGE = (0, 50)
FAILURES_BEFORE_SUSPEND_RANGE = (0, 100)
AUTO_SUSPEND_HOURS_RANGE = (1, 720)  # 1 hour to 30 days
COOLDOWN_MINUTES_RANGE = (0, 60)

DEFAULTS = {
    "free_requests_per_day": 10,
    "free_generations_per_user": 3,  # 1 account = 3 free, strict
    "copy_generations_per_user": 1,  # «Сделать такую же»: 1 free per account
    "default_rate_limit_per_hour": 20,
    "subscriber_rate_limit_per_hour": 100,
    "new_user_first_day_limit": 5,
    "max_failures_before_auto_suspend": 15,
    "auto_suspend_hours": 24,
    "cooldown_minutes_after_failures": 10,
    "vip_bypass_rate_limit": False,
}


class SecuritySettingsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self) -> SecuritySettings | None:
        return self.db.query(SecuritySettings).filter(SecuritySettings.id == 1).first()

    def get_or_create(self) -> SecuritySettings:
        row = self.get()
        if row:
            return row
        row = SecuritySettings(id=1, **DEFAULTS)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def as_dict(self) -> dict[str, Any]:
        row = self.get_or_create()
        return {
            "free_requests_per_day": row.free_requests_per_day,
            "free_generations_per_user": getattr(row, "free_generations_per_user", 3),
            "copy_generations_per_user": getattr(row, "copy_generations_per_user", 1),
            "default_rate_limit_per_hour": row.default_rate_limit_per_hour,
            "subscriber_rate_limit_per_hour": row.subscriber_rate_limit_per_hour,
            "new_user_first_day_limit": row.new_user_first_day_limit,
            "max_failures_before_auto_suspend": row.max_failures_before_auto_suspend,
            "auto_suspend_hours": row.auto_suspend_hours,
            "cooldown_minutes_after_failures": row.cooldown_minutes_after_failures,
            "vip_bypass_rate_limit": row.vip_bypass_rate_limit,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def _validate_value(self, key: str, value: Any) -> Any:
        """Validate and clamp value to allowed range."""
        if value is None:
            return None
        ranges = {
            "free_requests_per_day": FREE_REQUESTS_RANGE,
            "free_generations_per_user": (1, 20),  # 1-20 free per account
            "copy_generations_per_user": (0, 5),  # 0-5 copy free per account
            "default_rate_limit_per_hour": RATE_LIMIT_RANGE,
            "subscriber_rate_limit_per_hour": RATE_LIMIT_RANGE,
            "new_user_first_day_limit": NEW_USER_LIMIT_RANGE,
            "max_failures_before_auto_suspend": FAILURES_BEFORE_SUSPEND_RANGE,
            "auto_suspend_hours": AUTO_SUSPEND_HOURS_RANGE,
            "cooldown_minutes_after_failures": COOLDOWN_MINUTES_RANGE,
        }
        if key in ranges and isinstance(value, (int, float)):
            lo, hi = ranges[key]
            return max(lo, min(hi, int(value)))
        if key == "vip_bypass_rate_limit":
            return bool(value)
        return value

    def update(self, data: dict[str, Any]) -> dict[str, Any]:
        row = self.get_or_create()
        for key in DEFAULTS:
            if key in data and data[key] is not None:
                validated = self._validate_value(key, data[key])
                setattr(row, key, validated)
        row.updated_at = datetime.now(timezone.utc)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return self.as_dict()
