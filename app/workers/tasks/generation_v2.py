"""
Celery task: generate image for a job (trend + user photo), save result, send to Telegram.
Bot calls: send_task("app.workers.tasks.generation_v2.generate_image", args=[job_id], kwargs={status_chat_id, status_message_id}).
Единый билдер: мастер prompt_input + трендовый prompt (без legacy-надстроек).
"""
import logging
import os
import time
from typing import Any
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.job import Job
from app.models.trend import Trend
from app.models.user import User
from app.paywall import decide_access, prepare_delivery
from app.paywall.keyboard import build_unlock_markup
from app.paywall.models import AccessContext
from app.services.app_settings.settings_service import AppSettingsService
from app.services.audit.service import AuditService
from app.services.generation_prompt.settings_service import (
    GenerationPromptSettingsService,
    clamp_top_p,
    normalize_aspect_ratio,
    normalize_media_resolution,
    normalize_seed,
    normalize_thinking_config,
    size_to_aspect_ratio,
)
from app.services.image_generation import (
    ImageGenerationError,
    ImageGenerationRequest,
    ImageProviderFactory,
    generate_with_retry,
)
from app.services.jobs.service import JobService
from app.services.product_analytics.service import ProductAnalyticsService
from app.services.telegram.client import TelegramClient
from app.services.telegram_messages.runtime import runtime_templates
from app.services.trends.service import TrendService
from app.utils.image_formats import aspect_ratio_to_size
from app.utils.metrics import (
    jobs_succeeded_total,
    jobs_failed_total,
    job_duration_seconds,
    generation_failed_total,
)

logger = logging.getLogger(__name__)


def _build_prompt_for_job(db: Session, job: Job, trend: Trend) -> tuple[str, str | None, str, str]:
    """
    Собрать промпт: мастер (prompt_input) + трендовый текст (секции / scene / system).
    Returns (prompt, negative_prompt, model, size).
    """
    gs = GenerationPromptSettingsService(db)
    effective = gs.get_effective(profile="release")
    model = effective.get("default_model", "gemini-2.5-flash-image")
    # Приоритет: выбор пользователя (job.image_size), иначе дефолт из админки (default_aspect_ratio → size)
    size = job.image_size or aspect_ratio_to_size(effective.get("default_aspect_ratio", "1:1"))

    sections = trend.prompt_sections if isinstance(trend.prompt_sections, list) else []
    trend_parts: list[str] = []
    if sections:
        for s in sorted(sections, key=lambda x: x.get("order", 0)):
            if not s.get("enabled") or not s.get("content"):
                continue
            content = str(s["content"]).strip()
            if content:
                trend_parts.append(content)
    trend_prompt = "\n\n".join(trend_parts).strip()
    if not trend_prompt:
        trend_prompt = (trend.scene_prompt or trend.system_prompt or "").strip()

    blocks = []

    prompt_input = (effective.get("prompt_input") or "").strip()
    if prompt_input:
        blocks.append(prompt_input)

    if trend_prompt:
        blocks.append(trend_prompt)
    prompt_text = "\n\n".join(blocks).strip()
    negative = None
    if trend.prompt_model:
        model = trend.prompt_model
    return prompt_text, negative, model, size


def _resolve_job_generation_config(
    *,
    trend: Trend | None,
    effective_release: dict[str, Any],
    model: str,
    size: str | None,
    prefer_size_aspect_ratio: bool,
) -> dict[str, Any]:
    trend_aspect_ratio = (getattr(trend, "prompt_aspect_ratio", None) or "").strip() if trend else ""
    trend_media_resolution = getattr(trend, "prompt_media_resolution", None) if trend else None
    trend_thinking_config = getattr(trend, "prompt_thinking_config", None) if trend else None
    trend_top_p = getattr(trend, "prompt_top_p", None) if trend else None
    trend_seed = getattr(trend, "prompt_seed", None) if trend else None

    aspect_ratio = ""
    if trend_aspect_ratio:
        aspect_ratio = normalize_aspect_ratio(trend_aspect_ratio, fallback="")
    if not aspect_ratio and prefer_size_aspect_ratio:
        aspect_ratio = size_to_aspect_ratio(size, fallback="1:1")
    if not aspect_ratio:
        aspect_ratio = normalize_aspect_ratio(effective_release.get("default_aspect_ratio"), fallback="3:4")
    top_p = clamp_top_p(trend_top_p if trend_top_p is not None else effective_release.get("default_top_p"))
    media_resolution = normalize_media_resolution(
        trend_media_resolution if trend_media_resolution is not None else effective_release.get("default_media_resolution")
    )
    thinking_source = trend_thinking_config if trend_thinking_config is not None else effective_release.get("default_thinking_config")
    thinking_config = normalize_thinking_config(model, thinking_source)
    seed = normalize_seed(trend_seed if trend_seed is not None else effective_release.get("default_seed"))

    return {
        "aspect_ratio": aspect_ratio,
        "top_p": top_p,
        "candidate_count": 1,  # Production flow is always single candidate.
        "media_resolution": media_resolution,
        "thinking_config": thinking_config,
        "seed": seed,
    }


@celery_app.task(bind=True, name="app.workers.tasks.generation_v2.generate_image")
def generate_image(
    self,
    job_id: str,
    status_chat_id: str | None = None,
    status_message_id: int | None = None,
) -> dict:
    """
    Load job, build prompt from trend + settings, call image provider, save file, update job, send photo to Telegram.
    On ImageGenerationError: log detail, send finish_message to user.
    """
    db: Session = SessionLocal()
    telegram = TelegramClient()
    started_at = time.time()
    try:
        job_service = JobService(db)
        job = job_service.get(job_id)
        if not job:
            logger.error("generation_v2_job_not_found", extra={"job_id": job_id})
            if status_chat_id:
                if status_message_id is not None:
                    telegram.edit_message(status_chat_id, status_message_id, "❌ Задача не найдена.")
                else:
                    telegram.send_message(status_chat_id, "❌ Задача не найдена.")
            return {"ok": False, "error": "job_not_found"}

        trend_svc = TrendService(db)
        trend = trend_svc.get(job.trend_id)
        if not trend:
            logger.error("generation_v2_trend_not_found", extra={"job_id": job_id, "trend_id": job.trend_id})
            job_service.set_status(job, "FAILED", error_code="trend_missing")
            try:
                AuditService(db).log(
                    actor_type="system",
                    actor_id=None,
                    action="job_failed",
                    entity_type="job",
                    entity_id=job_id,
                    payload={"error_code": "trend_missing"},
                )
            except Exception:
                logger.exception("generation_v2_audit_failed")
            trend_id_label = job.trend_id or "unknown"
            jobs_failed_total.labels(trend_id=trend_id_label, error_code="trend_missing").inc()
            generation_failed_total.labels(error_code="trend_missing", source="job").inc()
            ProductAnalyticsService(db).track(
                "generation_failed",
                job.user_id,
                job_id=job_id,
                trend_id=job.trend_id,
                properties={"error_code": "trend_missing", "latency_ms": int((time.time() - started_at) * 1000)},
            )
            if status_chat_id:
                if status_message_id is not None:
                    telegram.edit_message(status_chat_id, status_message_id, "❌ Тренд не найден.")
                else:
                    telegram.send_message(status_chat_id, "❌ Тренд не найден.")
            return {"ok": False, "error": "trend_missing"}

        job_service.set_status(job, "RUNNING")
        try:
            AuditService(db).log(
                actor_type="system",
                actor_id=None,
                action="job_started",
                entity_type="job",
                entity_id=job_id,
                payload={"trend_id": job.trend_id},
            )
        except Exception:
            logger.exception("generation_v2_audit_job_started_failed")

        if status_chat_id and status_message_id is not None:
            step1 = runtime_templates.get("progress.regenerate_step1", "⏳ Генерация изображения…")
            try:
                telegram.edit_message(status_chat_id, status_message_id, step1)
            except Exception as e:
                logger.debug("generation_v2_progress_edit_skip", extra={"error": str(e)})

        prompt_text, negative_prompt, model, size = _build_prompt_for_job(db, job, trend)
        input_image_path: str | None = None
        if job.input_local_paths:
            input_image_path = job.input_local_paths[0] if isinstance(job.input_local_paths[0], str) else None
        if not input_image_path or not os.path.isfile(input_image_path):
            input_image_path = None

        gs = GenerationPromptSettingsService(db)
        effective_job = gs.get_effective(profile="release")
        temperature = trend.prompt_temperature if trend.prompt_temperature is not None else effective_job.get("default_temperature")
        resolved_generation_cfg = _resolve_job_generation_config(
            trend=trend,
            effective_release=effective_job,
            model=model,
            size=size,
            prefer_size_aspect_ratio=bool((job.image_size or "").strip()),
        )
        image_size_tier = (getattr(trend, "prompt_image_size_tier", None) or "").strip() or effective_job.get("default_image_size_tier") or None

        app_svc = AppSettingsService(db)
        provider_override = app_svc.get_effective_provider(settings)
        provider_name = provider_override or getattr(settings, "image_provider", "gemini")
        provider = ImageProviderFactory.create_from_settings(settings, provider_name)
        ProductAnalyticsService(db).track(
            "generation_started",
            job.user_id,
            job_id=job_id,
            trend_id=job.trend_id,
            properties={"model": model, "provider": provider_name},
        )
        request = ImageGenerationRequest(
            prompt=prompt_text,
            model=model,
            size=size,
            negative_prompt=negative_prompt,
            input_image_path=input_image_path,
            extra_params=None,
            temperature=temperature,
            seed=resolved_generation_cfg["seed"],
            image_size_tier=image_size_tier,
            aspect_ratio=resolved_generation_cfg["aspect_ratio"],
            top_p=resolved_generation_cfg["top_p"],
            candidate_count=resolved_generation_cfg["candidate_count"],
            media_resolution=resolved_generation_cfg["media_resolution"],
            thinking_config=resolved_generation_cfg["thinking_config"],
        )
        try:
            AuditService(db).log(
                actor_type="system",
                actor_id=None,
                action="generation_request",
                entity_type="job",
                entity_id=job_id,
                payload={
                    "model": model,
                    "prompt_length": len(prompt_text) if prompt_text else 0,
                    "trend_id": job.trend_id,
                    "has_input_image": input_image_path is not None,
                },
            )
        except Exception:
            logger.exception("generation_v2_audit_request_failed")

        if status_chat_id and status_message_id is not None:
            step2 = runtime_templates.get("progress.regenerate_step2", "⏳ Почти готово…")
            try:
                telegram.edit_message(status_chat_id, status_message_id, step2)
            except Exception as e:
                logger.debug("generation_v2_progress_edit_skip", extra={"error": str(e)})

        try:
            result = generate_with_retry(
                provider,
                request,
                settings,
                model_version=model,
                safety_settings_snapshot=getattr(settings, "gemini_safety_settings", None),
                streaming_enabled=False,
                provider_name=provider_name,
            )
        except ImageGenerationError as e:
            logger.warning(
                "generation_v2_provider_error",
                extra={"job_id": job_id, "detail": e.detail, "error_message": str(e)},
            )
            job_service.set_status(job, "FAILED", error_code="generation_failed")
            try:
                AuditService(db).log(
                    actor_type="system",
                    actor_id=None,
                    action="generation_response",
                    entity_type="job",
                    entity_id=job_id,
                    payload={"finish_reason": "error", "error_code": "generation_failed"},
                )
                AuditService(db).log(
                    actor_type="system",
                    actor_id=None,
                    action="job_failed",
                    entity_type="job",
                    entity_id=job_id,
                    payload={"error_code": "generation_failed"},
                )
            except Exception:
                logger.exception("generation_v2_audit_failed")
            trend_id_label = job.trend_id or "unknown"
            jobs_failed_total.labels(trend_id=trend_id_label, error_code="generation_failed").inc()
            generation_failed_total.labels(error_code="generation_failed", source="job").inc()
            ProductAnalyticsService(db).track(
                "generation_failed",
                job.user_id,
                job_id=job_id,
                trend_id=job.trend_id,
                properties={
                    "error_code": "generation_failed",
                    "latency_ms": int((time.time() - started_at) * 1000),
                },
            )
            msg = (e.detail.get("finish_message") or str(e)) if e.detail else str(e)
            if status_chat_id:
                if status_message_id is not None:
                    telegram.edit_message(status_chat_id, status_message_id, f"❌ {msg[:4000]}")
                else:
                    telegram.send_message(status_chat_id, f"❌ {msg[:4000]}")
            return {"ok": False, "error": "generation_failed", "message": msg}

        # Save raw image with attempt suffix (immutable filenames for retry/regen)
        out_dir = os.path.join(settings.storage_base_path, "outputs")
        os.makedirs(out_dir, exist_ok=True)
        ext = "png" if (getattr(settings, "image_format", "png") or "png").lower() == "png" else "jpg"
        attempt = getattr(self, "request", None) and getattr(self.request, "retries", 0) or 0
        raw_path = os.path.join(out_dir, f"{job_id}_{attempt}.{ext}")
        with open(raw_path, "wb") as f:
            f.write(result.image_content)

        # Paywall: decide access -> prepare delivery
        user = db.query(User).filter(User.id == job.user_id).one_or_none()
        subscription_active = getattr(user, "subscription_active", False) if user else False
        is_unlocked = getattr(job, "unlocked_at", None) is not None
        ctx = AccessContext(
            user_id=job.user_id,
            subscription_active=subscription_active,
            used_free_quota=bool(job.used_free_quota),
            used_copy_quota=bool(job.used_copy_quota),
            is_unlocked=is_unlocked,
            reserved_tokens=job.reserved_tokens or 0,
        )
        decision = decide_access(ctx)
        delivery_result = prepare_delivery(
            decision, raw_path, out_dir, job_id, attempt, db=db
        )

        if delivery_result.is_preview and delivery_result.preview_path and delivery_result.original_path:
            job_service.set_output_with_paywall(
                job, delivery_result.preview_path, delivery_result.original_path
            )
            photo_path = delivery_result.preview_path
            has_hd = (
                getattr(user, "hd_credits_balance", 0) > 0
                and getattr(user, "hd_credits_debt", 0) == 0
            ) if user else False
            reply_markup = build_unlock_markup(
                job_id, delivery_result.unlock_options, show_hd_credits=has_hd,
            )
        else:
            job_service.set_output(job, delivery_result.original_path)
            photo_path = delivery_result.original_path
            reply_markup = None
        job_service.set_status(job, "SUCCEEDED")
        try:
            AuditService(db).log(
                actor_type="system",
                actor_id=None,
                action="generation_response",
                entity_type="job",
                entity_id=job_id,
                payload={"finish_reason": "success"},
            )
            AuditService(db).log(
                actor_type="system",
                actor_id=None,
                action="job_succeeded",
                entity_type="job",
                entity_id=job_id,
                payload={"trend_id": job.trend_id},
            )
        except Exception:
            logger.exception("generation_v2_audit_success_failed")
        duration = time.time() - started_at
        latency_ms = int(duration * 1000)
        trend_id_label = job.trend_id or "unknown"
        jobs_succeeded_total.labels(trend_id=trend_id_label).inc()
        job_duration_seconds.labels(trend_id=trend_id_label).observe(duration)
        ProductAnalyticsService(db).track(
            "generation_completed",
            job.user_id,
            job_id=job_id,
            trend_id=job.trend_id,
            properties={"model": model, "provider": provider_name, "latency_ms": latency_ms},
        )

        # Notify user: delete progress message, send photo (with unlock buttons if preview)
        if status_chat_id:
            if status_message_id is not None:
                try:
                    telegram.delete_message(status_chat_id, status_message_id)
                except Exception:
                    pass
            try:
                telegram.send_photo(status_chat_id, photo_path, caption=None, reply_markup=reply_markup)
            except Exception as e:
                logger.exception("generation_v2_send_photo_failed", extra={"job_id": job_id, "chat_id": status_chat_id})
                telegram.send_message(status_chat_id, f"✅ Генерация готова, но не удалось отправить фото: {e}")

        return {"ok": True, "job_id": job_id, "output_path": photo_path}
    except Exception:
        logger.exception("generate_image_fatal", extra={"job_id": job_id})
        generation_failed_total.labels(error_code="unexpected_error", source="job").inc()
        # Ensure job is not left in RUNNING (re-fetch to avoid inconsistent state)
        try:
            job_service = JobService(db)
            job = job_service.get(job_id)
            if job and job.status in ("CREATED", "RUNNING"):
                job_service.set_status(job, "FAILED", error_code="unexpected_error")
                try:
                    AuditService(db).log(
                        actor_type="system",
                        actor_id=None,
                        action="job_failed",
                        entity_type="job",
                        entity_id=job_id,
                        payload={"error_code": "unexpected_error"},
                    )
                except Exception:
                    logger.exception("generation_v2_audit_failed")
                jobs_failed_total.labels(
                    trend_id=job.trend_id or "unknown",
                    error_code="unexpected_error",
                ).inc()
        except Exception as e:
            logger.warning("generate_image_fatal_set_status_failed", extra={"job_id": job_id, "error": str(e)})
        if status_chat_id:
            try:
                telegram.send_message(status_chat_id, "❌ Произошла ошибка при генерации. Попробуйте ещё раз.")
            except Exception:
                pass
        return {"ok": False, "error": "unexpected_error"}
    finally:
        db.close()
        telegram.close()
