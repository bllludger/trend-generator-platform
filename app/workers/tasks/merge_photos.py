"""
Celery task: склейка 2-3 фотографий пользователя (PhotoMerge flow).
"""
import logging
import os
import time
from datetime import datetime, timezone

from app.core.celery_app import celery_app
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.photo_merge_job import PhotoMergeJob
from app.services.audit.service import AuditService
from app.services.photo_merge.service import PhotoMergeService
from app.services.photo_merge.settings_service import PhotoMergeSettingsService
from app.services.telegram.client import TelegramClient
from app.utils.telegram_photo import path_for_telegram_photo

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.workers.tasks.merge_photos.merge_photos",
    bind=True,
    max_retries=1,
    task_time_limit=120,
    soft_time_limit=100,
)
def merge_photos(self, job_id: str) -> dict:
    """
    Обработать задание склейки фото.
    job_id — id записи PhotoMergeJob в БД.
    """
    db = SessionLocal()
    telegram = TelegramClient()
    t_start = time.time()
    try:
        job: PhotoMergeJob | None = db.query(PhotoMergeJob).filter(PhotoMergeJob.id == job_id).first()
        if not job:
            logger.error("merge_photos_job_not_found", extra={"job_id": job_id})
            return {"ok": False, "error": "job_not_found"}

        user_id = job.user_id
        input_paths: list[str] = job.input_paths or []

        # Статус «в обработке»
        job.status = "processing"
        job.updated_at = datetime.now(timezone.utc)
        db.add(job)
        db.commit()

        # Загружаем настройки
        svc_settings = PhotoMergeSettingsService(db)
        cfg = svc_settings.as_dict()

        out_dir = os.path.join(settings.storage_base_path, "outputs", "merges")
        os.makedirs(out_dir, exist_ok=True)
        ext = "jpeg" if cfg["output_format"] == "jpeg" else "png"
        output_path = os.path.join(out_dir, f"merge_{job_id}.{ext}")

        merge_svc = PhotoMergeService()
        metrics = merge_svc.merge(
            input_paths=input_paths,
            output_path=output_path,
            output_format=cfg["output_format"],
            jpeg_quality=cfg["jpeg_quality"],
            max_output_side_px=cfg["max_output_side_px"],
            background_color=cfg["background_color"],
        )

        duration_ms = int((time.time() - t_start) * 1000)
        job.status = "succeeded"
        job.output_path = output_path
        job.input_bytes = metrics.get("input_bytes")
        job.output_bytes = metrics.get("output_bytes")
        job.duration_ms = duration_ms
        job.updated_at = datetime.now(timezone.utc)
        db.add(job)
        db.commit()

        AuditService(db).log(
            actor_type="system",
            actor_id="merge_photos",
            action="photo_merge_completed",
            entity_type="photo_merge_job",
            entity_id=job_id,
            payload={
                "user_id": user_id,
                "input_count": job.input_count,
                "duration_ms": duration_ms,
                "output_bytes": metrics.get("output_bytes"),
            },
        )
        db.commit()

        # Отправить пользователю как документ (без Telegram-компрессии)
        # Сначала progress-сообщение удаляем (если есть), затем отправляем документ
        try:
            photo_path, is_temp = path_for_telegram_photo(output_path)
            telegram.send_document(
                chat_id=user_id,
                document_path=photo_path,
                caption=(
                    "✅ Готово! Вот ваше фото.\n"
                    "Нажмите скачать — изображение в оригинальном качестве."
                ),
                filename=f"merge_{job.input_count}photos.{ext}",
            )
            if is_temp and os.path.isfile(photo_path):
                try:
                    os.remove(photo_path)
                except OSError:
                    pass
        except Exception as tg_err:
            logger.error("merge_photos_send_error", extra={"job_id": job_id, "error": str(tg_err)})

        return {
            "ok": True,
            "job_id": job_id,
            "output_path": output_path,
            "duration_ms": duration_ms,
        }

    except Exception as exc:
        duration_ms = int((time.time() - t_start) * 1000)
        logger.exception("merge_photos_failed", extra={"job_id": job_id})
        try:
            job = db.query(PhotoMergeJob).filter(PhotoMergeJob.id == job_id).first()
            if job:
                job.status = "failed"
                job.error_code = type(exc).__name__
                job.duration_ms = duration_ms
                job.updated_at = datetime.now(timezone.utc)
                db.add(job)
                db.commit()
                AuditService(db).log(
                    actor_type="system",
                    actor_id="merge_photos",
                    action="photo_merge_failed",
                    entity_type="photo_merge_job",
                    entity_id=job_id,
                    payload={"user_id": job.user_id, "error": str(exc)},
                )
                db.commit()
                # Уведомить пользователя об ошибке
                try:
                    telegram.send_message(
                        chat_id=job.user_id,
                        text="❌ Не удалось создать фото. Попробуйте ещё раз или вернитесь в меню.",
                    )
                except Exception:
                    pass
        except Exception:
            logger.exception("merge_photos_cleanup_error", extra={"job_id": job_id})
        return {"ok": False, "job_id": job_id, "error": str(exc)}
    finally:
        try:
            db.close()
        except Exception:
            pass
        try:
            telegram.close()
        except Exception:
            pass
