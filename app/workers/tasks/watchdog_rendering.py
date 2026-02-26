"""
Celery beat task: reset stuck favorites with hd_status='rendering' older than threshold.
For collection sessions with SLA: issues idempotent compensation (HD credit return).
For standalone sessions: simple reset to 'none'.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.exc import ProgrammingError

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.favorite import Favorite
from app.models.session import Session
from app.services.audit.service import AuditService

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
