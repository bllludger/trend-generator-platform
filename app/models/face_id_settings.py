from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String

from app.db.base import Base


class FaceIdSettings(Base):
    __tablename__ = "face_id_settings"

    id = Column(Integer, primary_key=True, default=1)
    enabled = Column(Boolean, nullable=False, default=True)
    min_detection_confidence = Column(Float, nullable=False, default=0.6)
    model_selection = Column(Integer, nullable=False, default=1)
    crop_pad_left = Column(Float, nullable=False, default=0.55)
    crop_pad_right = Column(Float, nullable=False, default=0.55)
    crop_pad_top = Column(Float, nullable=False, default=0.7)
    crop_pad_bottom = Column(Float, nullable=False, default=0.35)
    max_faces_allowed = Column(Integer, nullable=False, default=1)
    no_face_policy = Column(String(64), nullable=False, default="fallback_original")
    multi_face_policy = Column(String(64), nullable=False, default="fail_generation")
    callback_timeout_seconds = Column(Float, nullable=False, default=2.0)
    callback_max_retries = Column(Integer, nullable=False, default=3)
    callback_backoff_seconds = Column(Float, nullable=False, default=1.0)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
