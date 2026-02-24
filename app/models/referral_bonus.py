from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.db.base import Base


class ReferralBonus(Base):
    __tablename__ = "referral_bonuses"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    referrer_user_id = Column(String, nullable=False, index=True)
    referral_user_id = Column(String, nullable=False, index=True)
    payment_id = Column(String, nullable=False, index=True)
    pack_stars = Column(Integer, nullable=False)
    hd_credits_amount = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="pending")
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    available_at = Column(DateTime(timezone=True), nullable=False)
    spent_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoke_reason = Column(Text, nullable=True)
