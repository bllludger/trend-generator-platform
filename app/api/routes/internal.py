import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.take import Take
from app.services.audit.service import AuditService
from app.services.face_id.asset_service import FaceAssetService
from app.services.face_id.signature import verify_face_id_signature
from app.services.telegram.client import TelegramClient
from app.utils.metrics import (
    face_id_callback_total,
    face_id_fallback_total,
    face_id_pending_takes,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])


def _pending_takes_count(db: Session) -> int:
    return int(db.query(Take.id).filter(Take.status == "awaiting_face_id").count())


def _notify_chat(chat_id: str | None, text: str) -> None:
    if not chat_id:
        return
    telegram = TelegramClient()
    try:
        telegram.send_message(chat_id, text)
    except Exception:
        logger.exception("face_id_notify_chat_failed", extra={"chat_id": chat_id})
    finally:
        telegram.close()


@router.post("/face-id/callback")
async def face_id_callback(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    body = await request.body()
    ts = (request.headers.get("X-FaceId-Timestamp") or "").strip()
    sig = (request.headers.get("X-FaceId-Signature") or "").strip()
    if not ts or not sig:
        raise HTTPException(status_code=401, detail="missing signature headers")
    try:
        ts_i = int(ts)
    except ValueError as e:
        raise HTTPException(status_code=401, detail="invalid timestamp") from e
    ttl = int(getattr(settings, "face_id_signature_ttl_seconds", 300) or 300)
    now = int(time.time())
    if abs(now - ts_i) > ttl:
        raise HTTPException(status_code=401, detail="timestamp expired")
    if not verify_face_id_signature(settings.face_id_callback_secret, ts, body, sig):
        raise HTTPException(status_code=401, detail="bad signature")
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail="invalid json") from e

    asset_id = str(payload.get("asset_id") or "").strip()
    event_id = str(payload.get("event_id") or "").strip()
    status = str(payload.get("status") or "").strip()
    if not asset_id or not event_id or not status:
        raise HTTPException(status_code=400, detail="asset_id/event_id/status are required")
    if status not in {"ready", "ready_fallback", "failed_multi_face", "failed_error"}:
        raise HTTPException(status_code=400, detail="unsupported status")

    asset_svc = FaceAssetService(db)
    asset = asset_svc.get(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="asset not found")

    waiting_take = (
        db.query(Take)
        .filter(Take.face_asset_id == asset.id, Take.status == "awaiting_face_id")
        .order_by(Take.created_at.asc())
        .first()
    )
    is_duplicate = (asset.last_event_id or "") == event_id
    allow_duplicate_recovery = is_duplicate and status in {"ready", "ready_fallback"} and waiting_take is not None
    if is_duplicate and not allow_duplicate_recovery:
        face_id_callback_total.labels(status="duplicate").inc()
        return {"ok": True, "duplicate": True}

    faces_detected_raw = payload.get("faces_detected")
    faces_detected: int | None = None
    if faces_detected_raw is not None:
        try:
            faces_detected = int(faces_detected_raw)
        except (TypeError, ValueError):
            faces_detected = None
    selected_path = payload.get("selected_path")
    source_path = payload.get("source_path")
    detector_meta = payload.get("detector_meta") if isinstance(payload.get("detector_meta"), dict) else {}
    if not is_duplicate:
        asset_svc.apply_callback(
            asset=asset,
            event_id=event_id,
            status=status,
            faces_detected=faces_detected,
            selected_path=str(selected_path) if selected_path else None,
            source_path=str(source_path) if source_path else None,
            detector_meta=detector_meta,
        )
        db.commit()
        face_id_callback_total.labels(status=status).inc()
        if status == "ready_fallback":
            reason_label = str(asset.reason_code or "no_face")
            face_id_fallback_total.labels(reason=reason_label).inc()
        face_id_pending_takes.set(_pending_takes_count(db))

        try:
            AuditService(db).log(
                actor_type="system",
                actor_id="face_id_callback",
                action="face_asset_callback_received",
                entity_type="face_asset",
                entity_id=asset.id,
                payload={"status": status, "event_id": event_id, "faces_detected": faces_detected},
                user_id=asset.user_id,
                session_id=asset.session_id,
            )
        except Exception:
            logger.exception("face_asset_callback_audit_failed", extra={"asset_id": asset.id})

    if not waiting_take:
        return {"ok": True, "asset_id": asset.id, "status": status, "take": None}

    if status in {"ready", "ready_fallback"}:
        from app.core.celery_app import celery_app

        kwargs: dict[str, Any] = {}
        if asset.chat_id:
            kwargs["status_chat_id"] = str(asset.chat_id)
        try:
            celery_app.send_task(
                "app.workers.tasks.generate_take.generate_take",
                args=[waiting_take.id],
                kwargs=kwargs,
            )
        except Exception:
            logger.exception("face_id_callback_enqueue_failed", extra={"take_id": waiting_take.id, "asset_id": asset.id})
            raise HTTPException(status_code=503, detail="generation enqueue failed")

        waiting_take.status = "generating"
        db.add(waiting_take)
        db.commit()
        face_id_pending_takes.set(_pending_takes_count(db))
        _notify_chat(asset.chat_id, "✅ Фото подготовлено. Запускаю генерацию…")
        try:
            AuditService(db).log(
                actor_type="system",
                actor_id="face_id_callback",
                action="face_asset_applied_to_take",
                entity_type="take",
                entity_id=waiting_take.id,
                payload={"face_asset_id": asset.id, "status": status},
                user_id=waiting_take.user_id,
                session_id=waiting_take.session_id,
            )
        except Exception:
            logger.exception("face_asset_applied_audit_failed", extra={"take_id": waiting_take.id, "asset_id": asset.id})
        return {"ok": True, "asset_id": asset.id, "status": status, "take": waiting_take.id}

    if status == "failed_multi_face":
        try:
            from app.bot.handlers.generation import _mark_take_enqueue_failed

            _mark_take_enqueue_failed(waiting_take.id, actor_id="face_id_callback", reason="failed_multi_face")
        except Exception:
            logger.exception("face_id_failed_multi_face_mark_failed_error", extra={"take_id": waiting_take.id})
        _notify_chat(
            asset.chat_id,
            "❌ На фото обнаружено несколько лиц. Пожалуйста, загрузите селфи с одним человеком.",
        )
        try:
            AuditService(db).log(
                actor_type="system",
                actor_id="face_id_callback",
                action="face_asset_failed_multi_face",
                entity_type="take",
                entity_id=waiting_take.id,
                payload={"face_asset_id": asset.id},
                user_id=waiting_take.user_id,
                session_id=waiting_take.session_id,
            )
        except Exception:
            logger.exception("face_asset_multi_face_audit_failed", extra={"take_id": waiting_take.id, "asset_id": asset.id})
        face_id_pending_takes.set(_pending_takes_count(db))
        return {"ok": True, "asset_id": asset.id, "status": status, "take": waiting_take.id}

    try:
        from app.bot.handlers.generation import _mark_take_enqueue_failed

        _mark_take_enqueue_failed(waiting_take.id, actor_id="face_id_callback", reason="failed_error")
    except Exception:
        logger.exception("face_id_failed_error_mark_failed_error", extra={"take_id": waiting_take.id})
    _notify_chat(
        asset.chat_id,
        "⚠️ Не удалось подготовить фото автоматически. Попробуйте загрузить фото еще раз.",
    )
    face_id_pending_takes.set(_pending_takes_count(db))
    return {"ok": True, "asset_id": asset.id, "status": status, "take": waiting_take.id}
