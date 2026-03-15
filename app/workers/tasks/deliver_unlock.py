"""
Celery task: доставка разблокированного файла (unlock по ЮKassa) в Telegram.
Webhook только помечает order paid и ставит эту задачу; отправка файла здесь.
"""
import logging

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.audit.service import AuditService
from app.services.takes.service import TakeService
from app.services.telegram.client import TelegramClient
from app.services.unlock_order.service import UnlockOrderService, unlock_photo_display_filename

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.tasks.deliver_unlock.deliver_unlock_file", bind=True)
def deliver_unlock_file(self, order_id: str) -> dict:
    """
    Загрузить unlock_order (status=paid), получить original_path, отправить в Telegram, пометить delivered или delivery_failed.
    """
    db = SessionLocal()
    try:
        unlock_svc = UnlockOrderService(db)
        order, original_path = unlock_svc.get_order_for_delivery(order_id)
        if not order:
            logger.warning("deliver_unlock_order_not_found", extra={"order_id": order_id})
            return {"ok": False, "reason": "order_not_found"}
        if order.status == "delivered":
            return {"ok": True, "reason": "already_delivered"}
        if not original_path:
            unlock_svc.mark_delivery_failed(order_id)
            db.commit()
            try:
                AuditService(db).log(
                    actor_type="system",
                    actor_id=None,
                    action="unlock_delivery_failed",
                    entity_type="unlock_order",
                    entity_id=order_id,
                    payload={"reason": "no_path"},
                )
            except Exception:
                logger.exception("deliver_unlock_audit_failed")
            logger.warning("deliver_unlock_no_path", extra={"order_id": order_id})
            return {"ok": False, "reason": "no_path"}
        tg = TelegramClient()
        try:
            tg.send_document(
                int(order.telegram_user_id),
                original_path,
                caption=(
                    "🎉 Отличный выбор!\n\n"
                    "Вот ваш снимок\n"
                    "без водяных знаков\n"
                    "и в полном качестве.\n\n"
                    "Сохраните его —\n"
                    "он идеально подойдёт\n"
                    "для соцсетей."
                ),
                filename=unlock_photo_display_filename(order.id, original_path),
            )
        except Exception as e:
            logger.exception("deliver_unlock_send_failed", extra={"order_id": order_id, "error": str(e)})
            unlock_svc.mark_delivery_failed(order_id)
            db.commit()
            try:
                AuditService(db).log(
                    actor_type="system",
                    actor_id=None,
                    action="unlock_delivery_failed",
                    entity_type="unlock_order",
                    entity_id=order_id,
                    payload={"reason": "send_failed"},
                )
            except Exception:
                logger.exception("deliver_unlock_audit_failed")
            return {"ok": False, "reason": "send_failed", "error": str(e)}
        finally:
            tg.close()
        unlock_svc.mark_delivered(order_id)
        db.commit()
        try:
            AuditService(db).log(
                actor_type="system",
                actor_id=None,
                action="unlock_delivered",
                entity_type="unlock_order",
                entity_id=order_id,
                payload={},
            )
        except Exception:
            logger.exception("deliver_unlock_audit_failed")
        logger.info("deliver_unlock_delivered", extra={"order_id": order_id})
        return {"ok": True}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
