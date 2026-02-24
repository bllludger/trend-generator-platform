"""
Mass broadcast to bot users via Telegram.
Respects rate limits and excludes banned/suspended users.
"""
import logging
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.user import User
from app.services.telegram.client import TelegramClient

logger = logging.getLogger("broadcast")

# Telegram: ~30 msg/sec, we use 5/sec to be safe
DELAY_BETWEEN_MESSAGES = 0.2
MAX_MESSAGE_LENGTH = 4096


@celery_app.task(bind=True, name="app.workers.tasks.broadcast.broadcast_message")
def broadcast_message(self, message_text: str, include_blocked: bool = False) -> dict:
    """
    Send message to all bot users.
    Excludes banned and suspended by default.
    """
    if not message_text or not message_text.strip():
        return {"sent": 0, "failed": 0, "skipped": 0, "error": "empty_message"}

    text = message_text.strip()
    if len(text) > MAX_MESSAGE_LENGTH:
        return {"sent": 0, "failed": 0, "skipped": 0, "error": "message_too_long"}

    db: Session = SessionLocal()
    telegram = TelegramClient()

    try:
        now = datetime.now(timezone.utc)
        query = db.query(User.telegram_id, User.is_banned, User.is_suspended, User.suspended_until)
        users = query.all()

        to_send = []
        for tg_id, is_banned, is_suspended, suspended_until in users:
            if not include_blocked:
                if is_banned:
                    continue
                if is_suspended and suspended_until and now < suspended_until:
                    continue
            to_send.append(tg_id)

        total = len(to_send)
        sent = 0
        failed = 0

        for i, telegram_id in enumerate(to_send):
            try:
                telegram.send_message(str(telegram_id), text)
                sent += 1
                if (i + 1) % 50 == 0:
                    logger.info("broadcast_progress", extra={"sent": sent, "total": total})
            except Exception as e:
                failed += 1
                logger.warning(
                    "broadcast_fail",
                    extra={"telegram_id": telegram_id, "error": str(e)},
                )

            if i < len(to_send) - 1:
                time.sleep(DELAY_BETWEEN_MESSAGES)

        result = {
            "sent": sent,
            "failed": failed,
            "skipped": len(users) - total,
            "total_recipients": total,
        }
        logger.info("broadcast_completed", extra=result)
        return result
    finally:
        db.close()
        telegram.close()
