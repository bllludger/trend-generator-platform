from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base


class FaceAsset(Base):
    __tablename__ = "face_assets"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, nullable=False, index=True)
    session_id = Column(String, nullable=True, index=True)
    chat_id = Column(String, nullable=True)
    flow = Column(String(32), nullable=False, default="trend")
    source_path = Column(String, nullable=False)
    processed_path = Column(String, nullable=True)
    selected_path = Column(String, nullable=True)
    status = Column(String(32), nullable=False, default="pending")
    faces_detected = Column(Integer, nullable=True)
    primary_face_bbox = Column(JSONB, nullable=True)
    crop_bbox = Column(JSONB, nullable=True)
    reason_code = Column(String(64), nullable=True)
    request_id = Column(String(128), nullable=True, index=True)
    last_event_id = Column(String(128), nullable=True)
    latency_ms = Column(Integer, nullable=True)
    detector_meta = Column(JSONB, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

