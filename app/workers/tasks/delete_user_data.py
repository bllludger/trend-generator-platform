"""
Celery task: delete user data (files + DB paths) on /deletemydata request.
"""
import logging
import os
from datetime import datetime, timezone

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.favorite import Favorite
from app.models.session import Session
from app.models.take import Take
from app.models.user import User
from app.services.telegram.client import TelegramClient

logger = logging.getLogger(__name__)


def _safe_delete(path: str | None) -> bool:
    if not path:
        return False
    try:
        if os.path.isfile(path):
            os.unlink(path)
            return True
    except OSError:
        logger.warning("delete_user_data_file_error", extra={"path": path})
    return False


@celery_app.task(
    name="app.workers.tasks.delete_user_data.delete_user_data",
    time_limit=300,
    soft_time_limit=280,
)
def delete_user_data(user_id: str) -> dict:
    """Delete all user files and clear paths in DB."""
    db = SessionLocal()
    telegram = TelegramClient()
    deleted_files = 0
    try:
        user = db.query(User).filter(User.id == user_id).one_or_none()
        if not user:
            return {"ok": False, "error": "user_not_found"}

        sessions = db.query(Session).filter(Session.user_id == user_id).all()
        session_ids = [s.id for s in sessions]

        for session in sessions:
            if _safe_delete(session.input_photo_path):
                deleted_files += 1
            session.input_photo_path = None
            session.input_file_id = None
            db.add(session)

        if session_ids:
            takes = db.query(Take).filter(Take.session_id.in_(session_ids)).all()
        else:
            takes = db.query(Take).filter(Take.user_id == user_id).all()

        for take in takes:
            if take.input_local_paths and isinstance(take.input_local_paths, list):
                for p in take.input_local_paths:
                    if _safe_delete(p):
                        deleted_files += 1
                take.input_local_paths = None

            for attr in [
                "preview_a", "preview_b", "preview_c",
                "original_a", "original_b", "original_c",
            ]:
                path = getattr(take, attr, None)
                if _safe_delete(path):
                    deleted_files += 1
                if hasattr(take, attr):
                    setattr(take, attr, None)
            db.add(take)

        favorites = db.query(Favorite).filter(Favorite.user_id == user_id).all()
        for fav in favorites:
            for attr in ["preview_path", "original_path", "hd_path"]:
                path = getattr(fav, attr, None)
                if _safe_delete(path):
                    deleted_files += 1
            db.delete(fav)

        user.data_deletion_requested_at = datetime.now(timezone.utc)
        db.add(user)
        db.commit()

        try:
            telegram.send_message(
                str(user.telegram_id),
                "✅ Ваши данные удалены. Все файлы были стёрты с сервера.",
            )
        except Exception:
            logger.warning("delete_user_data_notify_failed", extra={"user_id": user_id})

        logger.info(
            "delete_user_data_complete",
            extra={"user_id": user_id, "deleted_files": deleted_files},
        )
        return {"ok": True, "deleted_files": deleted_files}
    except Exception:
        logger.exception("delete_user_data_error", extra={"user_id": user_id})
        db.rollback()
        return {"ok": False, "error": "unexpected_error"}
    finally:
        db.close()
        telegram.close()
