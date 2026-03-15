"""
Send a single Telegram message to a user (e.g. admin activation message after grant-pack).
"""
import logging

from app.core.celery_app import celery_app
from app.services.telegram.client import TelegramClient
from app.utils.metrics import telegram_send_failures_total

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 4096

# Retry: 3 attempts, exponential backoff 60s, 120s, 240s
SEND_USER_MESSAGE_RETRY_BACKOFF = True
SEND_USER_MESSAGE_MAX_RETRIES = 3


@celery_app.task(
    name="app.workers.tasks.send_user_message.send_telegram_to_user",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=SEND_USER_MESSAGE_MAX_RETRIES,
)
def send_telegram_to_user(telegram_id: str, text: str) -> dict:
    """
    Send a text message to one user by telegram_id.
    Used after admin grants a pack with an activation message.
    """
    if not text or not text.strip():
        return {"ok": False, "error": "empty_message"}
    if len(text) > MAX_MESSAGE_LENGTH:
        return {"ok": False, "error": "message_too_long"}
    try:
        client = TelegramClient()
        client.send_message(str(telegram_id), text.strip())
        logger.info("send_telegram_to_user_ok", extra={"telegram_id": telegram_id})
        return {"ok": True}
    except Exception as e:
        telegram_send_failures_total.labels(method="send_user_message").inc()
        logger.warning("send_telegram_to_user_failed", extra={"telegram_id": telegram_id, "error": str(e)})
        raise  # re-raise so Celery can retry
