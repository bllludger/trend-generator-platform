from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, String, Text

from app.db.base import Base


class TrafficSource(Base):
    __tablename__ = "traffic_sources"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    slug = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    url = Column(Text, nullable=True)
    platform = Column(String, nullable=False, default="other")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
