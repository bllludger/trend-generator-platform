"""
Celery task: deliver all available originals (A/B/C) for a paid trial bundle order.
"""
import logging
import os

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.idempotency import IdempotencyStore
from app.services.telegram.client import TelegramClient
from app.services.takes.service import TakeService
from app.services.trial_bundle_order.service import TrialBundleOrderService

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.tasks.deliver_trial_bundle.deliver_trial_bundle", bind=True)
def deliver_trial_bundle(self, order_id: str) -> dict:
    db = SessionLocal()
    tg = TelegramClient()
    lock_store = None
    lock_key = f"trial_bundle:deliver:{order_id}"
    lock_acquired = False
    try:
        try:
            lock_store = IdempotencyStore()
            lock_acquired = lock_store.check_and_set(lock_key, ttl_seconds=300)
        except Exception:
            # Fail-open: do not block delivery because Redis is temporarily unavailable.
            lock_store = None
            lock_acquired = True
        if not lock_acquired:
            return {"ok": True, "reason": "in_progress"}

        svc = TrialBundleOrderService(db)
        order = svc.get_by_id(order_id)
        if not order:
            return {"ok": False, "reason": "order_not_found"}
        if order.status == "delivered":
            return {"ok": True, "reason": "already_delivered"}
        if order.status not in ("paid", "delivery_failed"):
            return {"ok": False, "reason": f"bad_status:{order.status}"}

        take = TakeService(db).get_take(order.take_id)
        if not take:
            svc.mark_delivery_failed(order_id)
            db.commit()
            return {"ok": False, "reason": "take_not_found"}

        order_variants = list(getattr(order, "variants", None) or [])
        expected_variants = [v for v in ("A", "B", "C") if v in order_variants]
        if len(expected_variants) != 3:
            svc.mark_delivery_failed(order_id)
            db.commit()
            return {"ok": False, "reason": "invalid_order_variants"}

        paths: dict[str, str] = {}
        missing: list[str] = []
        for variant in expected_variants:
            _, original_path = TakeService(db).get_variant_paths(take, variant)
            if not original_path or not os.path.isfile(original_path):
                missing.append(variant)
            else:
                paths[variant] = original_path
        if missing:
            svc.mark_delivery_failed(order_id)
            db.commit()
            return {"ok": False, "reason": f"missing_originals:{','.join(missing)}"}

        sent = 0
        for variant in ("A", "B", "C"):
            try:
                tg.send_document(
                    int(order.telegram_user_id),
                    paths[variant],
                    caption=f"🖼 Вариант {variant} в полном качестве.",
                )
                sent += 1
            except Exception:
                svc.mark_delivery_failed(order_id)
                db.commit()
                logger.exception("deliver_trial_bundle_variant_send_failed", extra={"order_id": order_id, "variant": variant})
                return {"ok": False, "reason": f"send_failed:{variant}", "sent": sent}

        svc.mark_delivered(order_id)
        db.commit()
        return {"ok": True, "sent": sent}
    except Exception:
        db.rollback()
        logger.exception("deliver_trial_bundle_failed", extra={"order_id": order_id})
        return {"ok": False, "reason": "exception"}
    finally:
        if lock_store is not None and lock_acquired:
            try:
                lock_store.release(lock_key)
            except Exception:
                pass
        tg.close()
        db.close()
