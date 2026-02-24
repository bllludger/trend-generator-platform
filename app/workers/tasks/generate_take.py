"""
Celery task: generate a Take (3 preview variants A/B/C).

Each variant is generated sequentially with a different random seed.
Original (no watermark) is saved for HD upscale later.
Preview = downscale + watermark overlay.
"""
import logging
import os
import random
import time

from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.take import Take
from app.models.trend import Trend
from app.services.app_settings.settings_service import AppSettingsService
from app.services.generation_prompt.settings_service import GenerationPromptSettingsService
from app.services.image_generation import (
    ImageGenerationError,
    ImageGenerationRequest,
    ImageProviderFactory,
    generate_with_retry,
)
from app.services.audit.service import AuditService
from app.services.sessions.service import SessionService
from app.services.takes.service import TakeService
from app.services.telegram.client import TelegramClient
from app.services.transfer_policy.service import SCOPE_TRENDS, get_effective as transfer_get_effective
from app.services.trends.service import TrendService
from app.paywall.watermark import apply_watermark

logger = logging.getLogger(__name__)

VARIANTS = ["A", "B", "C"]
RATE_LIMIT_DELAY = 1.5
MAX_VARIANT_RETRIES = 2
VARIANT_RETRY_DELAY = 2.0

# Reply-клавиатура (меню внизу чата), совпадает с main_menu_keyboard в боте
MAIN_MENU_REPLY = {
    "keyboard": [
        [{"text": "🔥 Создать фото"}, {"text": "🔄 Сделать такую же"}],
        [{"text": "🛒 Купить генерации"}, {"text": "👤 Мой профиль"}],
    ],
    "resize_keyboard": True,
}


def _style_preset_to_text(style_preset) -> str:
    if style_preset is None:
        return ""
    if isinstance(style_preset, str):
        return (style_preset or "").strip()
    if isinstance(style_preset, dict):
        return " ".join(f"{k}: {v}" for k, v in sorted(style_preset.items()) if v)
    return ""


def _build_prompt_for_take(db: Session, take: Take, trend: Trend) -> tuple[str, str | None, str, str]:
    """Build prompt from trend + master settings. Returns (prompt, negative, model, size)."""
    gs = GenerationPromptSettingsService(db)
    effective = gs.get_effective()
    model = effective.get("default_model", "gemini-2.5-flash-image")
    size = take.image_size or effective.get("default_size", "1024x1024")
    fmt = effective.get("default_format", "png")

    sections = trend.prompt_sections if isinstance(trend.prompt_sections, list) else []
    if sections:
        parts = []
        for s in sorted(sections, key=lambda x: x.get("order", 0)):
            if s.get("enabled") and s.get("content"):
                parts.append(str(s["content"]).strip())
        prompt_text = "\n\n".join(parts) if parts else (trend.scene_prompt or trend.system_prompt or "Generate image.")
        negative = trend.negative_prompt or None
        if trend.prompt_model:
            model = trend.prompt_model
        if trend.prompt_size:
            size = trend.prompt_size
        return prompt_text, negative, model, size

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
    composition = (transfer.get("composition_rules_text") or "").strip()
    if composition:
        blocks.append(f"[COMPOSITION]\n{composition}")
    scene = (trend.scene_prompt or trend.system_prompt or "").strip()
    if scene:
        blocks.append(f"[SCENE]\n{scene}")
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


def _downscale_and_watermark(original_path: str, preview_path: str) -> str:
    """Create preview: downscale to max 800px + apply watermark."""
    from PIL import Image as PILImage

    img = PILImage.open(original_path)
    max_dim = 800
    if max(img.size) > max_dim:
        ratio = max_dim / max(img.size)
        new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
        img = img.resize(new_size, PILImage.LANCZOS)
    downscaled_tmp = preview_path + ".tmp.png"
    img.save(downscaled_tmp, "PNG")
    img.close()

    apply_watermark(downscaled_tmp, preview_path)
    try:
        os.unlink(downscaled_tmp)
    except OSError:
        pass
    return preview_path


@celery_app.task(
    bind=True,
    name="app.workers.tasks.generate_take.generate_take",
    time_limit=180,
    soft_time_limit=170,
)
def generate_take(
    self,
    take_id: str,
    status_chat_id: str | None = None,
    status_message_id: int | None = None,
) -> dict:
    """Generate 3 preview variants (A/B/C) for a Take."""
    db: Session = SessionLocal()
    telegram = TelegramClient()
    try:
        take_svc = TakeService(db)
        session_svc = SessionService(db)

        take = take_svc.get_take(take_id)
        if not take:
            logger.error("generate_take_not_found", extra={"take_id": take_id})
            if status_chat_id and status_message_id:
                telegram.edit_message(status_chat_id, status_message_id, "❌ Задача не найдена.")
            return {"ok": False, "error": "take_not_found"}

        trend_svc = TrendService(db)
        trend = trend_svc.get(take.trend_id) if take.trend_id else None

        if take.take_type == "CUSTOM" and take.custom_prompt:
            prompt_text = take.custom_prompt
            negative_prompt = None
            model = "gemini-2.5-flash-image"
            size = take.image_size or "1024x1024"
        elif trend:
            prompt_text, negative_prompt, model, size = _build_prompt_for_take(db, take, trend)
        else:
            logger.error("generate_take_no_trend", extra={"take_id": take_id})
            take_svc.set_status(take, "failed", error_code="trend_missing")
            if status_chat_id and status_message_id:
                telegram.edit_message(status_chat_id, status_message_id, "❌ Тренд не найден.")
            return {"ok": False, "error": "trend_missing"}

        input_image_path = None
        if take.input_local_paths:
            candidate = take.input_local_paths[0] if isinstance(take.input_local_paths[0], str) else None
            if candidate and os.path.isfile(candidate):
                input_image_path = candidate

        temperature = None
        if trend and trend.prompt_temperature is not None:
            temperature = trend.prompt_temperature

        app_svc = AppSettingsService(db)
        provider_override = app_svc.get_effective_provider(settings)
        provider = ImageProviderFactory.create_from_settings(settings, provider_override or "gemini")

        out_dir = os.path.join(settings.storage_base_path, "outputs")
        os.makedirs(out_dir, exist_ok=True)

        results = {}
        seeds = {}
        failed_variants = []

        for i, variant in enumerate(VARIANTS):
            if i > 0:
                time.sleep(RATE_LIMIT_DELAY)

            seed = random.randint(0, 2**31 - 1)
            seeds[variant] = seed

            success = False
            for attempt in range(MAX_VARIANT_RETRIES + 1):
                if attempt > 0:
                    time.sleep(VARIANT_RETRY_DELAY * (2 ** (attempt - 1)))

                try:
                    req = ImageGenerationRequest(
                        prompt=prompt_text,
                        model=model,
                        size=size,
                        negative_prompt=negative_prompt,
                        input_image_path=input_image_path,
                        temperature=temperature,
                        seed=seed,
                        image_size_tier="1K",
                    )
                    result = generate_with_retry(
                        provider,
                        req,
                        settings,
                        model_version=model,
                        safety_settings_snapshot=getattr(settings, "gemini_safety_settings", None),
                        streaming_enabled=False,
                    )

                    ext = "png"
                    original_path = os.path.join(out_dir, f"{take_id}_{variant}_original.{ext}")
                    with open(original_path, "wb") as f:
                        f.write(result.image_content)

                    preview_path = os.path.join(out_dir, f"{take_id}_{variant}_preview.{ext}")
                    _downscale_and_watermark(original_path, preview_path)

                    results[variant] = {
                        "original": original_path,
                        "preview": preview_path,
                    }
                    success = True
                    break

                except ImageGenerationError as e:
                    logger.warning(
                        "generate_take_variant_error",
                        extra={"take_id": take_id, "variant": variant, "attempt": attempt, "error": str(e)},
                    )
                except Exception as e:
                    logger.warning(
                        "generate_take_variant_unexpected",
                        extra={"take_id": take_id, "variant": variant, "attempt": attempt, "error": str(e)},
                    )

            if not success:
                failed_variants.append(variant)

        if not results:
            take_svc.set_status(take, "failed", error_code="all_variants_failed", error_variants=failed_variants)
            db.commit()
            if status_chat_id:
                if status_message_id:
                    telegram.edit_message(status_chat_id, status_message_id, "❌ Генерация не удалась.")
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "🔄 Попробовать ещё раз", "callback_data": "take_more"}],
                        [{"text": "📋 В меню", "callback_data": "error_action:menu"}],
                    ]
                }
                telegram.send_message(status_chat_id, "Попробуйте снова или вернитесь в меню.", reply_markup=keyboard)
            return {"ok": False, "error": "all_variants_failed"}

        take_svc.set_variants(
            take,
            preview_a=results.get("A", {}).get("preview"),
            preview_b=results.get("B", {}).get("preview"),
            preview_c=results.get("C", {}).get("preview"),
            original_a=results.get("A", {}).get("original"),
            original_b=results.get("B", {}).get("original"),
            original_c=results.get("C", {}).get("original"),
            seed_a=seeds.get("A"),
            seed_b=seeds.get("B"),
            seed_c=seeds.get("C"),
        )

        status = "ready" if not failed_variants else "partial_fail"
        take_svc.set_status(take, status, error_variants=failed_variants if failed_variants else None)

        if take.session_id:
            session = session_svc.get_session(take.session_id)
            if session:
                session_svc.use_take(session)

        audit = AuditService(db)
        audit.log(
            actor_type="system",
            actor_id="generate_take",
            action="take_previews_ready",
            entity_type="take",
            entity_id=take_id,
            payload={
                "session_id": take.session_id,
                "variants_count": len(results),
                "status": status,
                "failed_variants": failed_variants,
            },
        )

        db.commit()

        if status_chat_id:
            if status_message_id:
                try:
                    telegram.delete_message(status_chat_id, status_message_id)
                except Exception:
                    pass

            media = []
            available_variants = []
            for variant in VARIANTS:
                if variant in results:
                    media.append({
                        "type": "photo",
                        "media_path": results[variant]["preview"],
                        "caption": variant,
                    })
                    available_variants.append(variant)

            if media:
                try:
                    telegram.send_media_group(status_chat_id, media)
                except Exception as e:
                    logger.exception("generate_take_send_media_group_failed", extra={"take_id": take_id})
                    telegram.send_message(status_chat_id, f"✅ Снимок готов, но не удалось отправить фото: {e}")

            buttons_row = []
            for v in available_variants:
                buttons_row.append({"text": f"⭐ {v}", "callback_data": f"choose:{take_id}:{v}"})

            keyboard = {
                "inline_keyboard": [
                    buttons_row,
                    [
                        {"text": "📸 Ещё снимок", "callback_data": "take_more"},
                        {"text": "📋 Избранное", "callback_data": "open_favorites"},
                    ],
                ]
            }
            telegram.send_message(
                status_chat_id,
                "Выберите лучший вариант:",
                reply_markup=keyboard,
            )
            # Восстанавливаем reply-меню внизу чата (после генерации оно пропадает)
            telegram.send_message(
                status_chat_id,
                "👇 Меню ниже",
                reply_markup=MAIN_MENU_REPLY,
            )

        return {"ok": True, "take_id": take_id, "status": status, "variants": list(results.keys())}
    except Exception:
        logger.exception("generate_take_fatal", extra={"take_id": take_id})
        try:
            take = take_svc.get_take(take_id)
            if take and take.status == "generating":
                take_svc.set_status(take, "failed", error_code="unexpected_error")
                db.commit()
        except Exception:
            pass
        if status_chat_id:
            try:
                telegram.send_message(status_chat_id, "❌ Произошла ошибка при генерации. Попробуйте ещё раз.")
                telegram.send_message(status_chat_id, "👇 Меню ниже", reply_markup=MAIN_MENU_REPLY)
            except Exception:
                pass
        return {"ok": False, "error": "unexpected_error"}
    finally:
        db.close()
        telegram.close()
