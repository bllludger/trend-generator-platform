"""
Celery task: deliver HD version of a favorited preview.

HD = upscale of the original_no_watermark image (same image, higher resolution).
No re-rendering — guarantees "what you picked is what you get".
"""
import logging
import os

from app.core.celery_app import celery_app
from app.core.config import settings
from app.db.session import SessionLocal
from app.services.audit.service import AuditService
from app.services.favorites.service import FavoriteService
from app.services.hd_balance.service import HDBalanceService
from app.services.telegram.client import TelegramClient
from app.models.user import User

logger = logging.getLogger(__name__)


def _upscale_image(original_path: str, hd_path: str, scale: int = 2) -> str:
    """Upscale image using Pillow Lanczos. MVP approach — simple and reliable."""
    from PIL import Image as PILImage

    img = PILImage.open(original_path)
    new_size = (img.size[0] * scale, img.size[1] * scale)
    img_hd = img.resize(new_size, PILImage.LANCZOS)
    img_hd.save(hd_path, "PNG", quality=95)
    img.close()
    img_hd.close()
    return hd_path


@celery_app.task(
    bind=True,
    name="app.workers.tasks.deliver_hd.deliver_hd",
    time_limit=60,
    soft_time_limit=50,
)
def deliver_hd(
    self,
    favorite_id: str,
    status_chat_id: str | None = None,
    status_message_id: int | None = None,
) -> dict:
    """Upscale original and deliver HD to user."""
    db = SessionLocal()
    telegram = TelegramClient()
    try:
        fav_svc = FavoriteService(db)
        hd_svc = HDBalanceService(db)

        fav = fav_svc.get_favorite(favorite_id)
        if not fav:
            logger.error("deliver_hd_fav_not_found", extra={"favorite_id": favorite_id})
            return {"ok": False, "error": "favorite_not_found"}

        if fav.hd_status == "delivered":
            logger.info("deliver_hd_already_delivered", extra={"favorite_id": favorite_id})
            if status_chat_id and fav.hd_path and os.path.isfile(fav.hd_path):
                try:
                    telegram.send_document(status_chat_id, fav.hd_path, caption="🖼 HD версия (повтор)")
                except Exception:
                    pass
            return {"ok": True, "already_delivered": True}

        if not fav_svc.mark_rendering(favorite_id):
            logger.info("deliver_hd_already_rendering", extra={"favorite_id": favorite_id})
            return {"ok": False, "error": "already_rendering"}

        if not fav.original_path or not os.path.isfile(fav.original_path):
            logger.error("deliver_hd_original_missing", extra={"favorite_id": favorite_id})
            fav_svc.reset_hd_status(favorite_id)
            db.commit()
            if status_chat_id:
                telegram.send_message(status_chat_id, "❌ Оригинал не найден. Попробуйте заново.")
            return {"ok": False, "error": "original_missing"}

        user = db.query(User).filter(User.id == fav.user_id).one_or_none()
        if not user:
            fav_svc.reset_hd_status(favorite_id)
            db.commit()
            return {"ok": False, "error": "user_not_found"}

        out_dir = os.path.join(settings.storage_base_path, "outputs")
        os.makedirs(out_dir, exist_ok=True)
        hd_path = os.path.join(out_dir, f"{fav.take_id}_{fav.variant}_hd.png")

        try:
            _upscale_image(fav.original_path, hd_path)
        except Exception as e:
            logger.exception("deliver_hd_upscale_failed", extra={"favorite_id": favorite_id})
            fav_svc.reset_hd_status(favorite_id)
            db.commit()
            if status_chat_id:
                telegram.send_message(status_chat_id, "❌ Ошибка при создании HD версии. Попробуйте ещё раз.")
            return {"ok": False, "error": "upscale_failed"}

        if not hd_svc.spend(user, 1):
            logger.warning("deliver_hd_insufficient_balance", extra={"favorite_id": favorite_id, "user_id": user.id})
            fav_svc.reset_hd_status(favorite_id)
            try:
                os.unlink(hd_path)
            except OSError:
                pass
            db.commit()
            if status_chat_id:
                telegram.send_message(status_chat_id, "❌ Недостаточно HD на балансе.")
            return {"ok": False, "error": "insufficient_hd_balance"}

        fav_svc.mark_hd_delivered(favorite_id, hd_path)

        audit = AuditService(db)
        audit.log(
            actor_type="system",
            actor_id="deliver_hd",
            action="hd_delivered",
            entity_type="favorite",
            entity_id=favorite_id,
            payload={"session_id": fav.session_id, "take_id": fav.take_id, "variant": fav.variant},
        )

        db.commit()

        if status_chat_id:
            if status_message_id:
                try:
                    telegram.delete_message(status_chat_id, status_message_id)
                except Exception:
                    pass
            try:
                telegram.send_document(status_chat_id, hd_path, caption="🖼 HD версия готова!")
            except Exception as e:
                logger.exception("deliver_hd_send_failed", extra={"favorite_id": favorite_id})
                telegram.send_message(status_chat_id, f"✅ HD готова, но не удалось отправить: {e}")

        return {"ok": True, "favorite_id": favorite_id, "hd_path": hd_path}
    except Exception:
        logger.exception("deliver_hd_fatal", extra={"favorite_id": favorite_id})
        try:
            fav_svc.reset_hd_status(favorite_id)
            db.commit()
        except Exception:
            pass
        if status_chat_id:
            try:
                telegram.send_message(status_chat_id, "❌ Ошибка. Попробуйте ещё раз.")
            except Exception:
                pass
        return {"ok": False, "error": "unexpected_error"}
    finally:
        db.close()
        telegram.close()
