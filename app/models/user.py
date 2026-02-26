from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    telegram_id = Column(String, unique=True, nullable=False, index=True)
    telegram_username = Column(String, nullable=True)   # @nickname
    telegram_first_name = Column(String, nullable=True)
    telegram_last_name = Column(String, nullable=True)
    token_balance = Column(Integer, nullable=False, default=0)
    # NB: управляется вручную админом (нет автоматической подписки через Stars).
    # Влияет на rate-limit: подписчик получает subscriber_rate_limit_per_hour.
    subscription_active = Column(Boolean, nullable=False, default=False)
    free_generations_used = Column(Integer, nullable=False, default=0)  # 1 account = 3 free total
    copy_generations_used = Column(Integer, nullable=False, default=0)  # «Сделать такую же»: 1 free
    total_purchased = Column(Integer, nullable=False, default=0)  # всего куплено генераций (Stars)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Security / Moderation fields
    is_banned = Column(Boolean, nullable=False, default=False)
    ban_reason = Column(Text, nullable=True)
    banned_at = Column(DateTime(timezone=True), nullable=True)
    banned_by = Column(String, nullable=True)
    
    is_suspended = Column(Boolean, nullable=False, default=False)
    suspended_until = Column(DateTime(timezone=True), nullable=True)
    suspend_reason = Column(Text, nullable=True)
    
    rate_limit_per_hour = Column(Integer, nullable=True)  # null = use global default

    is_moderator = Column(Boolean, nullable=False, default=False)  # модератор: без лимитов (free/copy/токены/rate)

    admin_notes = Column(Text, nullable=True)
    flags = Column(JSONB, nullable=False, default=dict)  # VIP, tester, etc

    # Referral program
    referral_code = Column(String, unique=True, nullable=True)
    referred_by_user_id = Column(String, nullable=True)
    referred_at = Column(DateTime(timezone=True), nullable=True)
    hd_credits_balance = Column(Integer, nullable=False, default=0)
    hd_credits_pending = Column(Integer, nullable=False, default=0)
    hd_credits_debt = Column(Integer, nullable=False, default=0)
    has_purchased_hd = Column(Boolean, nullable=False, default=False)

    # Session-based HD balance (MVP)
    hd_paid_balance = Column(Integer, nullable=False, default=0)
    hd_promo_balance = Column(Integer, nullable=False, default=0)
    free_takes_used = Column(Integer, nullable=False, default=0)
    trial_purchased = Column(Boolean, nullable=False, default=False)

    # Consent & data deletion
    consent_accepted_at = Column(DateTime(timezone=True), nullable=True)
    data_deletion_requested_at = Column(DateTime(timezone=True), nullable=True)
    
    def is_access_blocked(self) -> bool:
        """Check if user access is blocked (banned or suspended)."""
        if self.is_banned:
            return True
        if self.is_suspended and self.suspended_until:
            return datetime.now(timezone.utc) < self.suspended_until
        return False
    
    def get_effective_rate_limit(self, default: int = 20, subscriber_limit: int = 100) -> int:
        """Get effective rate limit for this user. Модератор без лимита."""
        if getattr(self, "is_moderator", False):
            return 100_000
        if self.rate_limit_per_hour is not None:
            return self.rate_limit_per_hour
        return subscriber_limit if self.subscription_active else default
