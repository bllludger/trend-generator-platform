from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, String

from app.db.base import Base


class ReferralTrialReward(Base):
    __tablename__ = "referral_trial_rewards"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    referrer_user_id = Column(String, nullable=False, index=True)
    referral_user_id = Column(String, nullable=False, index=True)
    reason = Column(String, nullable=False, default="first_preview")
    rewarded_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

