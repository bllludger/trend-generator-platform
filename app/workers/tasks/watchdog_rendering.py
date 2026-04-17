"""
Celery beat task: reset stuck favorites with hd_status='rendering' older than threshold.
For collection sessions with SLA: issues idempotent compensation (HD credit return).
For standalone sessions: simple reset to 'none'.
"""
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.exc import ProgrammingError

from app.core.celery_app import celery_app
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.face_asset import FaceAsset
from app.models.favorite import Favorite
from app.models.session import Session
from app.models.take import Take
from app.services.audit.service import AuditService
from app.utils.metrics import favorites_hd_stuck_rendering_reset_total, face_id_pending_takes

logger = logging.getLogger(__name__)

STUCK_THRESHOLD_MINUTES = 10


@celery_app.task(
    name="app.workers.tasks.watchdog_rendering.reset_stuck_rendering",
    time_limit=60,
    soft_time_limit=55,
)
def reset_stuck_rendering() -> dict:
    """Find favorites stuck in 'rendering' and handle per-favorite:
    - Collection sessions with SLA → idempotent compensation via CompensationService
    - Standalone sessions → simple reset to 'none'
    """
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=STUCK_THRESHOLD_MINUTES)

        stuck_favs = (
            db.query(Favorite)
            .filter(
                Favorite.hd_status == "rendering",
                Favorite.updated_at < cutoff,
            )
            .all()
        )

        if not stuck_favs:
            return {"ok": True, "reset_count": 0, "compensated_count": 0}

        from app.services.compensations.service import CompensationService

        comp_svc = CompensationService(db)
        reset_count = 0
        compensated_count = 0

        for fav in stuck_favs:
            session = (
                db.query(Session)
                .filter(Session.id == fav.session_id)
                .one_or_none()
            ) if fav.session_id else None

            is_collection = (
                session is not None
                and session.playlist is not None
                and isinstance(session.playlist, list)
                and len(session.playlist) > 0
            )

            if is_collection:
                issued = comp_svc.check_and_compensate_hd_sla(fav.id)
                if issued:
                    compensated_count += 1
                else:
                    fav.hd_status = "none"
                    db.add(fav)
                    reset_count += 1
            else:
                fav.hd_status = "none"
                db.add(fav)
                reset_count += 1
            favorites_hd_stuck_rendering_reset_total.inc()

        db.commit()

        if reset_count > 0 or compensated_count > 0:
            logger.warning(
                "watchdog_reset_stuck_rendering",
                extra={"reset_count": reset_count, "compensated_count": compensated_count},
            )
        return {
            "ok": True,
            "reset_count": reset_count,
            "compensated_count": compensated_count,
        }
    except ProgrammingError as e:
        msg = str(e.orig) if getattr(e, "orig", None) else str(e)
        if "does not exist" in msg or "UndefinedTable" in msg:
            db.rollback()
            return {"ok": True, "skipped": "table_not_found"}
        logger.exception("watchdog_rendering_error")
        db.rollback()
        return {"ok": False}
    except Exception:
        logger.exception("watchdog_rendering_error")
        db.rollback()
        return {"ok": False}
    finally:
        db.close()


ABANDON_HOURS = 24


@celery_app.task(
    name="app.workers.tasks.watchdog_rendering.detect_collection_drops",
    time_limit=60,
    soft_time_limit=55,
)
def detect_collection_drops() -> dict:
    """Detect abandoned collection sessions (active but no activity for 24h)."""
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=ABANDON_HOURS)
        stale_sessions = (
            db.query(Session)
            .filter(
                Session.status == "active",
                Session.playlist.isnot(None),
                Session.updated_at < cutoff,
            )
            .all()
        )

        count = 0
        audit = AuditService(db)
        for sess in stale_sessions:
            playlist = sess.playlist
            if not isinstance(playlist, list) or len(playlist) == 0:
                continue
            if (sess.current_step or 0) >= len(playlist):
                continue

            audit.log(
                actor_type="system",
                actor_id="watchdog",
                action="collection_drop_step",
                entity_type="session",
                entity_id=sess.id,
                payload={
                    "step_dropped_at": sess.current_step,
                    "total_steps": len(playlist),
                    "collection_run_id": sess.collection_run_id,
                },
            )
            sess.status = "abandoned"
            db.add(sess)
            count += 1

        db.commit()
        if count > 0:
            logger.info("detect_collection_drops", extra={"abandoned_count": count})
        return {"ok": True, "abandoned_count": count}
    except ProgrammingError as e:
        msg = str(e.orig) if getattr(e, "orig", None) else str(e)
        if "does not exist" in msg or "UndefinedTable" in msg:
            db.rollback()
            return {"ok": True, "skipped": "table_not_found"}
        logger.exception("detect_collection_drops_error")
        db.rollback()
        return {"ok": False}
    except Exception:
        logger.exception("detect_collection_drops_error")
        db.rollback()
        return {"ok": False}
    finally:
        db.close()


def _resolve_take_fallback_input_path(db, take: Take) -> str | None:
    if take.session_id:
        session = db.query(Session).filter(Session.id == take.session_id).one_or_none()
        if session and session.input_photo_path and os.path.isfile(session.input_photo_path):
            return session.input_photo_path
    if isinstance(take.input_local_paths, list) and take.input_local_paths:
        candidate = take.input_local_paths[0] if isinstance(take.input_local_paths[0], str) else None
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


@celery_app.task(
    name="app.workers.tasks.watchdog_rendering.recover_stuck_face_id_takes",
    time_limit=60,
    soft_time_limit=55,
)
def recover_stuck_face_id_takes() -> dict:
    """
    Recover takes waiting for face-id too long:
    - if processed asset already ready -> enqueue generation
    - if still pending -> fallback to original image and enqueue
    - if multi-face/error/no image -> fail with compensation path
    """
    db = SessionLocal()
    try:
        timeout_seconds = max(30, int(getattr(settings, "face_id_await_timeout_seconds", 180) or 180))
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
        stuck_takes = (
            db.query(Take)
            .filter(Take.status == "awaiting_face_id", Take.created_at < cutoff)
            .order_by(Take.created_at.asc())
            .all()
        )
        if not stuck_takes:
            face_id_pending_takes.set(int(db.query(Take.id).filter(Take.status == "awaiting_face_id").count()))
            return {"ok": True, "recovered": 0, "failed": 0}

        from app.bot.handlers.generation import _mark_take_enqueue_failed

        recovered = 0
        failed = 0
        for take in stuck_takes:
            asset = None
            if take.face_asset_id:
                asset = db.query(FaceAsset).filter(FaceAsset.id == take.face_asset_id).one_or_none()

            if asset and asset.status in {"failed_multi_face", "failed_error"}:
                _mark_take_enqueue_failed(take.id, actor_id="face_id_watchdog", reason=str(asset.status))
                failed += 1
                continue

            selected_path = None
            if asset and asset.status in {"ready", "ready_fallback"} and asset.selected_path and os.path.isfile(asset.selected_path):
                selected_path = asset.selected_path
            if not selected_path and asset and asset.source_path and os.path.isfile(asset.source_path):
                selected_path = asset.source_path
                asset.status = "ready_fallback"
                asset.selected_path = selected_path
                asset.reason_code = "watchdog_timeout_fallback"
                db.add(asset)
            if not selected_path:
                selected_path = _resolve_take_fallback_input_path(db, take)
                if asset and selected_path:
                    asset.status = "ready_fallback"
                    asset.selected_path = selected_path
                    asset.reason_code = "watchdog_timeout_fallback"
                    db.add(asset)
            if not selected_path:
                _mark_take_enqueue_failed(take.id, actor_id="face_id_watchdog", reason="missing_input_after_timeout")
                failed += 1
                continue

            kwargs = {}
            if asset and asset.chat_id:
                kwargs["status_chat_id"] = str(asset.chat_id)
            try:
                celery_app.send_task(
                    "app.workers.tasks.generate_take.generate_take",
                    args=[take.id],
                    kwargs=kwargs,
                )
            except Exception:
                logger.exception("face_id_watchdog_enqueue_failed", extra={"take_id": take.id, "asset_id": take.face_asset_id})
                continue

            take.status = "generating"
            db.add(take)
            recovered += 1

        db.commit()
        face_id_pending_takes.set(int(db.query(Take.id).filter(Take.status == "awaiting_face_id").count()))
        if recovered or failed:
            logger.warning("face_id_watchdog_processed", extra={"recovered": recovered, "failed": failed})
        return {"ok": True, "recovered": recovered, "failed": failed}
    except Exception:
        logger.exception("face_id_watchdog_error")
        db.rollback()
        return {"ok": False}
    finally:
        db.close()
