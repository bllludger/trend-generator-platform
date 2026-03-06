"""Product analytics events — funnel, quality, trends, attribution."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base


class ProductEvent(Base):
    __tablename__ = "product_events"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    event_name = Column(String, nullable=False)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String, nullable=True, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    trend_id = Column(String, nullable=True)
    pack_id = Column(String, nullable=True)
    source = Column(String, nullable=True)
    campaign_id = Column(String, nullable=True)
    creative_id = Column(String, nullable=True)
    deep_link_id = Column(String, nullable=True)
    device_type = Column(String, nullable=True)
    country = Column(String, nullable=True)
    take_id = Column(String, nullable=True)
    job_id = Column(String, nullable=True)
    entity_type = Column(String, nullable=True)
    entity_id = Column(String, nullable=True)
    properties = Column(JSONB, nullable=False, default=dict)
