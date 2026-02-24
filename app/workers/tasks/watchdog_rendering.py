"""
Celery beat task: reset stuck favorites with hd_status='rendering' older than 10 minutes.
Prevents users from being permanently blocked when a deliver_hd task crashes.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.exc import ProgrammingError

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.favorite import Favorite

logger = logging.getLogger(__name__)

STUCK_THRESHOLD_MINUTES = 10


@celery_app.task(
    name="app.workers.tasks.watchdog_rendering.reset_stuck_rendering",
    time_limit=30,
    soft_time_limit=25,
)
def reset_stuck_rendering() -> dict:
    """Find favorites stuck in 'rendering' for > 10 min and reset to 'none'."""
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=STUCK_THRESHOLD_MINUTES)
        result = db.execute(
            update(Favorite)
            .where(
                Favorite.hd_status == "rendering",
                Favorite.updated_at < cutoff,
            )
            .values(hd_status="none")
        )
        count = result.rowcount
        db.commit()
        if count > 0:
            logger.warning("watchdog_reset_stuck_rendering", extra={"count": count})
        return {"ok": True, "reset_count": count}
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
