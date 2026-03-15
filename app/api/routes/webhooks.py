"""
Webhooks от внешних сервисов (ЮKassa и т.д.).
Без авторизации — проверка по payload/подписи по возможности.
"""
import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.pack_order.service import PackOrderService
from app.services.payments.service import PaymentService
from app.services.unlock_order.service import UnlockOrderService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _escape_markdown(s: str) -> str:
    """Экранировать символы для parse_mode='Markdown' (Telegram)."""
    if not s:
        return s
    for char, replacement in (("\\", "\\\\"), ("*", "\\*"), ("_", "\\_"), ("`", "\\`"), ("[", "\\[")):
        s = s.replace(char, replacement)
    return s


def _send_pack_success_message(
    chat_id: str,
    pack_emoji: str,
    pack_name: str,
    remaining: int,
    takes_limit: int,
    pending_4k_reminder: bool = False,
) -> None:
    """Отправить поздравление об активации пакета в Telegram — только текст, без кнопок."""
    safe_emoji = _escape_markdown(str(pack_emoji or ""))
    safe_name = _escape_markdown(str(pack_name or ""))
    count_line = f"Доступно фото: {remaining} из {takes_limit}. " if takes_limit > 0 else ""
    instruction = (
        "Один снимок — в этом шаге: выберите лучший из трёх вариантов выше.\n\n"
        "Вернитесь выше в чате и выберите лучший снимок — тогда получите его в полном качестве без водяного знака."
    )
    if pending_4k_reminder:
        instruction = "Вы уже выбрали снимок — вернитесь к сообщению с кнопкой «Открыть фото в 4K» и нажмите её.\n\n" + instruction
    text = (
        "🎉 *Оплата подтверждена.*\n\n"
        f"Пакет {safe_emoji} {safe_name} активирован.\n\n"
        f"{count_line}{instruction}"
    )
    try:
        from app.services.telegram.client import TelegramClient
        tg = TelegramClient()
        try:
            tg.send_message(chat_id, text, parse_mode="Markdown")
        finally:
            tg.close()
    except Exception as e:
        logger.exception(
            "yookassa_webhook_pack_send_message_failed",
            extra={"chat_id": chat_id, "error": str(e)},
        )


@router.post("/yookassa")
async def yookassa_webhook(request: Request, db: Session = Depends(get_db)):
    """
    ЮKassa notification: payment.succeeded.
    Сначала поиск unlock_order по object.id (yookassa_payment_id) — доставка файла.
    Если не найден — поиск pack_order: активация пакета и отправка поздравления.
    Ответ 200 всегда (чтобы ЮKassa не ретраил).
    """
    try:
        body = await request.json()
    except Exception as e:
        logger.warning("yookassa_webhook_invalid_json", extra={"error": str(e)})
        return JSONResponse(content={"received": True}, status_code=200)

    event = body.get("event") or ""
    obj = body.get("object") or {}
    payment_id = obj.get("id")
    status = obj.get("status") or ""
    logger.info(
        "yookassa_webhook_received",
        extra={"event": event, "payment_id": payment_id, "status": status},
    )

    # Обработка отмены/неуспеха платежа — заказ не висит в payment_pending вечно
    if event == "payment.canceled" and payment_id:
        unlock_svc = UnlockOrderService(db)
        u_order = unlock_svc.get_by_yookassa_payment_id(payment_id)
        if u_order and u_order.status in ("created", "payment_pending"):
            try:
                unlock_svc.mark_canceled(yookassa_payment_id=payment_id)
                db.commit()
                logger.info("yookassa_webhook_unlock_canceled", extra={"order_id": u_order.id, "payment_id": payment_id})
            except Exception as e:
                logger.exception("yookassa_webhook_unlock_mark_canceled_failed", extra={"order_id": u_order.id})
                db.rollback()
        else:
            pack_order_svc = PackOrderService(db)
            p_order = pack_order_svc.get_by_yookassa_payment_id(payment_id)
            if p_order and p_order.status in ("created", "payment_pending"):
                try:
                    pack_order_svc.mark_canceled(yookassa_payment_id=payment_id)
                    db.commit()
                    logger.info("yookassa_webhook_pack_canceled", extra={"order_id": p_order.id, "payment_id": payment_id})
                except Exception as e:
                    logger.exception("yookassa_webhook_pack_mark_canceled_failed", extra={"order_id": p_order.id})
                    db.rollback()
        return JSONResponse(content={"received": True}, status_code=200)

    if event != "payment.succeeded":
        return JSONResponse(content={"received": True}, status_code=200)
    if not payment_id or status != "succeeded":
        return JSONResponse(content={"received": True}, status_code=200)

    unlock_svc = UnlockOrderService(db)
    order = unlock_svc.get_by_yookassa_payment_id(payment_id)

    if order is not None:
        # Unlock (разблокировка одного фото)
        if order.status not in ("created", "payment_pending"):
            return JSONResponse(content={"received": True}, status_code=200)
        try:
            unlock_svc.mark_paid(order_id=order.id)
            payment_svc = PaymentService(db)
            payment_svc.record_yookassa_unlock_payment(order)
            db.commit()
        except Exception as e:
            logger.exception("yookassa_webhook_mark_paid_failed", extra={"order_id": order.id})
            db.rollback()
            return JSONResponse(content={"received": True}, status_code=200)
        try:
            from app.core.celery_app import celery_app
            celery_app.send_task(
                "app.workers.tasks.deliver_unlock.deliver_unlock_file",
                args=[order.id],
            )
            logger.info("yookassa_webhook_deliver_enqueued", extra={"order_id": order.id, "payment_id": payment_id})
        except Exception as e:
            logger.exception("yookassa_webhook_celery_send_failed", extra={"order_id": order.id, "error": str(e)})
        return JSONResponse(content={"received": True}, status_code=200)

    # Pack order (покупка пакета по ссылке)
    pack_order_svc = PackOrderService(db)
    pack_order = pack_order_svc.get_by_yookassa_payment_id(payment_id)
    if not pack_order:
        logger.warning("yookassa_webhook_order_not_found", extra={"payment_id": payment_id})
        return JSONResponse(content={"received": True}, status_code=200)
    if pack_order.status not in ("created", "payment_pending"):
        return JSONResponse(content={"received": True}, status_code=200)

    try:
        pack_order_svc.mark_paid(yookassa_payment_id=payment_id)
        db.commit()
    except Exception as e:
        logger.exception("yookassa_webhook_pack_mark_paid_failed", extra={"order_id": pack_order.id})
        db.rollback()
        return JSONResponse(content={"received": True}, status_code=200)

    payment_svc = PaymentService(db)
    payment_obj, session, trial_err, _ = payment_svc.process_session_purchase_yookassa_link(
        telegram_user_id=pack_order.telegram_user_id,
        pack_id=pack_order.pack_id,
        yookassa_payment_id=payment_id,
        amount_kopecks=pack_order.amount_kopecks,
    )
    if payment_obj is None or session is None:
        logger.warning(
            "yookassa_webhook_pack_activate_failed",
            extra={"order_id": pack_order.id, "trial_err": trial_err},
        )
        return JSONResponse(content={"received": True}, status_code=200)
    try:
        pack_order_svc.mark_completed(pack_order.id)
        db.commit()
    except Exception as e:
        logger.exception("yookassa_webhook_pack_mark_completed_failed", extra={"order_id": pack_order.id})
        db.rollback()

    pack = payment_svc.get_pack(pack_order.pack_id)
    pack_emoji = getattr(pack, "emoji", "") if pack else ""
    pack_name = getattr(pack, "name", pack_order.pack_id) if pack else pack_order.pack_id
    remaining = (session.takes_limit or 0) - (session.takes_used or 0)
    takes_limit = session.takes_limit or 0

    from app.services.users.service import UserService
    from app.services.favorites.service import FavoriteService
    user = UserService(db).get_by_telegram_id(pack_order.telegram_user_id)
    has_pending_4k = False
    if user:
        last_pending = FavoriteService(db).get_last_pending_hd_favorite(user.id)
        has_pending_4k = last_pending is not None

    _send_pack_success_message(
        pack_order.telegram_user_id,
        pack_emoji,
        pack_name,
        remaining,
        takes_limit,
        pending_4k_reminder=has_pending_4k,
    )
    logger.info("yookassa_webhook_pack_completed", extra={"order_id": pack_order.id, "payment_id": payment_id})
    return JSONResponse(content={"received": True}, status_code=200)
