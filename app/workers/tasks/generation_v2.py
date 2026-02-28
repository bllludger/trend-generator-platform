"""
Celery task: generate image for a job (trend + user photo), save result, send to Telegram.
Bot calls: send_task("app.workers.tasks.generation_v2.generate_image", args=[job_id], kwargs={status_chat_id, status_message_id}).
Единый билдер: [INPUT], [TASK], [IDENTITY TRANSFER], [COMPOSITION], [], [STYLE], [AVOID], [SAFETY], [OUTPUT].
"""
import logging
import os
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
from app.services.generation_prompt.settings_service import GenerationPromptSettingsService
from app.services.image_generation import (
    ImageGenerationError,
    ImageGenerationRequest,
    ImageProviderFactory,
    generate_with_retry,
)
from app.services.jobs.service import JobService
from app.services.telegram.client import TelegramClient
from app.services.telegram_messages.runtime import runtime_templates
from app.services.transfer_policy.service import SCOPE_TRENDS, get_effective as transfer_get_effective
from app.services.trends.service import TrendService

logger = logging.getLogger(__name__)


def _style_preset_to_text(style_preset) -> str:
    """Сериализовать style_preset (dict или str) в текст для блока [STYLE]."""
    if style_preset is None:
        return ""
    if isinstance(style_preset, str):
        return (style_preset or "").strip()
    if isinstance(style_preset, dict):
        return " ".join(f"{k}: {v}" for k, v in sorted(style_preset.items()) if v)
    return ""


def _build_prompt_for_job(db: Session, job: Job, trend: Trend) -> tuple[str, str | None, str, str]:
    """
    Собрать промпт: мастер (INPUT, TASK, SAFETY) + Transfer для трендов (IDENTITY, COMPOSITION, AVOID) + тренд (SCENE, STYLE, AVOID).
    Returns (prompt, negative_prompt, model, size).
    """
    gs = GenerationPromptSettingsService(db)
    effective = gs.get_effective()
    model = effective.get("default_model", "gemini-2.5-flash-image")
    size = job.image_size or effective.get("default_size", "1024x1024")
    fmt = effective.get("default_format", "png")

    # Если у тренда prompt_sections (Playground) — собираем из секций с тегами [], [STYLE], [AVOID], [COMPOSITION]
    sections = trend.prompt_sections if isinstance(trend.prompt_sections, list) else []
    if sections:
        label_to_tag = {"scene": "[]", "style": "[STYLE]", "avoid": "[AVOID]", "composition": "[COMPOSITION]"}
        parts = []
        for s in sorted(sections, key=lambda x: x.get("order", 0)):
            if not s.get("enabled") or not s.get("content"):
                continue
            content = str(s["content"]).strip()
            if not content:
                continue
            label = (s.get("label") or "").strip().lower()
            tag = label_to_tag.get(label)
            if tag:
                parts.append(f"{tag}\n{content}")
            else:
                parts.append(content)
        prompt_text = "\n\n".join(parts) if parts else (trend.scene_prompt or trend.system_prompt or "Generate image.")
        negative = trend.negative_prompt or None
        if trend.prompt_model:
            model = trend.prompt_model
        if trend.prompt_size:
            size = trend.prompt_size
        return prompt_text, negative, model, size

    # Единый порядок блоков: INPUT, TASK, IDENTITY, COMPOSITION, SCENE, STYLE, AVOID, SAFETY, OUTPUT
    transfer = transfer_get_effective(db, SCOPE_TRENDS)
    blocks = []

    prompt_input = (effective.get("prompt_input") or "").strip()
    if prompt_input:
        blocks.append(f"[INPUT]\n{prompt_input}")

    prompt_task = (effective.get("prompt_task") or "").strip()
    if prompt_task:
        blocks.append(f"[TASK]\n{prompt_task}")

    identity = (transfer.get("identity_rules_text") or "").strip()
    if identity:
        blocks.append(f"[IDENTITY TRANSFER]\n{identity}")

    composition = (getattr(trend, "composition_prompt", None) or "").strip() or (transfer.get("composition_rules_text") or "").strip()
    if composition:
        blocks.append(f"[COMPOSITION]\n{composition}")

    scene = (trend.scene_prompt or trend.system_prompt or "").strip()
    if scene:
        blocks.append(f"[]\n{scene}")

    style_text = _style_preset_to_text(trend.style_preset)
    if style_text:
        blocks.append(f"[STYLE]\n{style_text}")

    avoid_parts = []
    avoid_default = (transfer.get("avoid_default_items") or "").strip()
    if avoid_default:
        for line in avoid_default.replace(";", "\n").splitlines():
            item = line.strip()
            if item:
                avoid_parts.append(item)
    negative_scene = (trend.negative_scene or "").strip()
    if negative_scene:
        avoid_parts.append(negative_scene)
    if avoid_parts:
        blocks.append(f"[AVOID]\n{'; '.join(avoid_parts)}")

    safety = (effective.get("safety_constraints") or "").strip()
    if safety:
        blocks.append(f"[SAFETY]\n{safety}")
    blocks.append(f"[OUTPUT]\nsize={size}, format={fmt}")

    prompt_text = "\n\n".join(blocks)
    negative = (trend.negative_prompt or "").strip() or None
    return prompt_text, negative, model, size


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
            if status_chat_id:
                if status_message_id is not None:
                    telegram.edit_message(status_chat_id, status_message_id, "❌ Тренд не найден.")
                else:
                    telegram.send_message(status_chat_id, "❌ Тренд не найден.")
            return {"ok": False, "error": "trend_missing"}

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

        temperature = trend.prompt_temperature if trend.prompt_temperature is not None else None
        seed = int(trend.prompt_seed) if trend.prompt_seed is not None else None
        image_size_tier = getattr(trend, "prompt_image_size_tier", None) or None

        app_svc = AppSettingsService(db)
        provider_override = app_svc.get_effective_provider(settings)
        provider = ImageProviderFactory.create_from_settings(settings, provider_override or "gemini")
        request = ImageGenerationRequest(
            prompt=prompt_text,
            model=model,
            size=size,
            negative_prompt=negative_prompt,
            input_image_path=input_image_path,
            extra_params=None,
            temperature=temperature,
            seed=seed,
            image_size_tier=image_size_tier,
        )

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
            )
        except ImageGenerationError as e:
            logger.warning(
                "generation_v2_provider_error",
                extra={"job_id": job_id, "detail": e.detail, "error_message": str(e)},
            )
            job_service.set_status(job, "FAILED", error_code="generation_failed")
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
        delivery_result = prepare_delivery(decision, raw_path, out_dir, job_id, attempt)

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
    finally:
        db.close()
        telegram.close()
