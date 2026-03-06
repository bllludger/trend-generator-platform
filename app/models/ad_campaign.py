from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Numeric, String, Text

from app.db.base import Base


class AdCampaign(Base):
    __tablename__ = "ad_campaigns"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    source_id = Column(String, ForeignKey("traffic_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=True)
    budget_rub = Column(Numeric(12, 2), nullable=False, default=0)
    date_from = Column(Date, nullable=False)
    date_to = Column(Date, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    notes = Column(Text, nullable=True)
