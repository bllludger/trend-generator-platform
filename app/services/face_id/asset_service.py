from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.face_asset import FaceAsset


class FaceAssetService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, asset_id: str) -> FaceAsset | None:
        return self.db.query(FaceAsset).filter(FaceAsset.id == asset_id).one_or_none()

    def create_pending(
        self,
        *,
        user_id: str,
        session_id: str | None,
        chat_id: str | None,
        flow: str,
        source_path: str,
        request_id: str | None,
    ) -> FaceAsset:
        asset = FaceAsset(
            id=str(uuid4()),
            user_id=user_id,
            session_id=session_id,
            chat_id=chat_id,
            flow=flow,
            source_path=source_path,
            status="pending",
            selected_path=source_path,
            request_id=request_id,
        )
        self.db.add(asset)
        self.db.flush()
        return asset

    def set_session_if_missing(self, asset: FaceAsset, session_id: str | None) -> None:
        if session_id and not asset.session_id:
            asset.session_id = session_id
            self.db.add(asset)
            self.db.flush()

    def apply_callback(
        self,
        *,
        asset: FaceAsset,
        event_id: str,
        status: str,
        faces_detected: int | None,
        selected_path: str | None,
        source_path: str | None,
        detector_meta: dict[str, Any] | None,
    ) -> FaceAsset:
        asset.last_event_id = event_id
        asset.status = status
        asset.faces_detected = faces_detected
        if source_path:
            asset.source_path = source_path
        if selected_path:
            asset.selected_path = selected_path
        elif status == "failed_multi_face":
            asset.selected_path = None
        if isinstance(detector_meta, dict):
            asset.detector_meta = detector_meta
            if isinstance(detector_meta.get("bbox"), dict):
                asset.primary_face_bbox = detector_meta.get("bbox")
            if isinstance(detector_meta.get("crop_bbox"), dict):
                asset.crop_bbox = detector_meta.get("crop_bbox")
            latency_raw = detector_meta.get("latency_ms")
            if latency_raw is not None:
                try:
                    asset.latency_ms = int(latency_raw)
                except (TypeError, ValueError):
                    pass
        if status == "ready":
            asset.processed_path = selected_path
        if status == "ready_fallback":
            reason = None
            if isinstance(detector_meta, dict):
                reason = str(detector_meta.get("reason") or "").strip()
            asset.reason_code = reason or "no_face_fallback"
            asset.processed_path = None
        elif status == "failed_multi_face":
            asset.reason_code = "multi_face_detected"
        elif status == "failed_error":
            asset.reason_code = "processing_error"
        asset.updated_at = datetime.now(timezone.utc)
        self.db.add(asset)
        self.db.flush()
        return asset

    def list_recent(self, limit: int = 100) -> list[FaceAsset]:
        safe_limit = max(1, min(500, int(limit)))
        return (
            self.db.query(FaceAsset)
            .order_by(FaceAsset.created_at.desc())
            .limit(safe_limit)
            .all()
        )
