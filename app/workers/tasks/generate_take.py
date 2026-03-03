"""
Celery task: generate a Take (3 preview variants A/B/C).

Variants can be generated sequentially (take_generation_parallel_workers=1) or in parallel
via ThreadPoolExecutor (2 or 3 workers). Original (no watermark) is saved for HD upscale later.
Preview = downscale + watermark overlay.
"""
import logging
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.take import Take
from app.models.trend import Trend
from app.models.user import User
from app.services.balance_tariffs import build_balance_tariffs_message
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
from app.services.telegram_messages.runtime import runtime_templates

# Путь к картинке «баланс + тарифы» (image/money2.png); в Docker нужен volume ./image:/app/image
_WORKER_ROOT = os.path.dirname(os.path.abspath(__file__))
MONEY_IMAGE_PATH = os.path.normpath(os.path.join(_WORKER_ROOT, "..", "..", "..", "image", "money2.png"))
from app.services.transfer_policy.service import SCOPE_TRENDS, get_effective as transfer_get_effective
from app.services.trends.service import TrendService
from app.utils.image_formats import aspect_ratio_to_size
from app.utils.telegram_photo import path_for_telegram_photo
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
        [{"text": "🛒 Купить тариф"}, {"text": "👤 Мой профиль"}],
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


def _build_prompt_for_take(db: Session, take: Take, trend: Trend) -> tuple[str, str | None, str, str, str | None]:
    """Build prompt from trend + master settings. Returns (prompt, negative, model, size, image_size_tier)."""
    gs = GenerationPromptSettingsService(db)
    effective = gs.get_effective(profile="release")
    model = effective.get("default_model", "gemini-2.5-flash-image")
    # Приоритет: выбор пользователя (take.image_size), иначе дефолт из админки (default_aspect_ratio → size)
    size = take.image_size or aspect_ratio_to_size(effective.get("default_aspect_ratio", "1:1"))
    fmt = effective.get("default_format", "png")
    image_size_tier = (getattr(trend, "prompt_image_size_tier", None) or "").strip() or effective.get("default_image_size_tier") or "4K"

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
        tier = (getattr(trend, "prompt_image_size_tier", None) or "").strip() or image_size_tier
        return prompt_text, negative, model, size, tier

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
    return prompt_text, negative, model, size, image_size_tier


def _downscale_and_watermark(
    original_path: str,
    preview_path: str,
    max_dim: int = 800,
    watermark_params: dict | None = None,
) -> str:
    """Create preview: downscale to max_dim px + apply watermark. max_dim и watermark_params из админки (app_settings)."""
    from PIL import Image as PILImage

    img = PILImage.open(original_path)
    if max(img.size) > max_dim:
        ratio = max_dim / max(img.size)
        new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
        img = img.resize(new_size, PILImage.LANCZOS)
    downscaled_tmp = preview_path + ".tmp.png"
    img.save(downscaled_tmp, "PNG")
    img.close()

    apply_watermark(downscaled_tmp, preview_path, params=watermark_params)
    try:
        os.unlink(downscaled_tmp)
    except OSError:
        pass
    return preview_path


def _generate_one_variant(
    *,
    settings,
    provider_override: str | None,
    out_dir: str,
    take_id: str,
    variant: str,
    seed: int,
    prompt_text: str,
    model: str,
    size: str,
    negative_prompt: str | None,
    input_image_path: str | None,
    temperature: float | None,
    image_size_tier: str,
    max_dim: int,
    watermark_params: dict,
) -> tuple[str, int, dict | None]:
    """
    Сгенерировать один вариант (A/B/C) в потоке. Возвращает (variant, seed, result_dict) или (variant, seed, None) при ошибке.
    Создаёт свой экземпляр провайдера в потоке (thread-safe).
    """
    ext = "png"
    original_path = os.path.join(out_dir, f"{take_id}_{variant}_original.{ext}")
    preview_path = os.path.join(out_dir, f"{take_id}_{variant}_preview.{ext}")
    for attempt in range(MAX_VARIANT_RETRIES + 1):
        if attempt > 0:
            time.sleep(VARIANT_RETRY_DELAY * (2 ** (attempt - 1)))
        try:
            provider = ImageProviderFactory.create_from_settings(settings, provider_override or "gemini")
            req = ImageGenerationRequest(
                prompt=prompt_text,
                model=model,
                size=size,
                negative_prompt=negative_prompt,
                input_image_path=input_image_path,
                temperature=temperature,
                seed=seed,
                image_size_tier=image_size_tier,
            )
            result = generate_with_retry(
                provider,
                req,
                settings,
                model_version=model,
                safety_settings_snapshot=getattr(settings, "gemini_safety_settings", None),
                streaming_enabled=False,
            )
            with open(original_path, "wb") as f:
                f.write(result.image_content)
            _downscale_and_watermark(
                original_path,
                preview_path,
                max_dim=max_dim,
                watermark_params=watermark_params,
            )
            return (variant, seed, {"original": original_path, "preview": preview_path})
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
    return (variant, seed, None)


# Лимиты: 3 варианта × (до 2 попыток каждый) × ~60–90 с на генерацию — запас 400/420 с
@celery_app.task(
    bind=True,
    name="app.workers.tasks.generate_take.generate_take",
    time_limit=420,
    soft_time_limit=400,
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
            gs_custom = GenerationPromptSettingsService(db)
            effective_custom = gs_custom.get_effective(profile="release")
            prompt_text = take.custom_prompt
            negative_prompt = None
            model = "gemini-2.5-flash-image"
            size = take.image_size or aspect_ratio_to_size(effective_custom.get("default_aspect_ratio", "1:1"))
            image_size_tier = effective_custom.get("default_image_size_tier") or "4K"
        elif trend:
            prompt_text, negative_prompt, model, size, image_size_tier = _build_prompt_for_take(db, take, trend)
        else:
            logger.error("generate_take_no_trend", extra={"take_id": take_id})
            take_svc.set_status(take, "failed", error_code="trend_missing")
            if status_chat_id and status_message_id:
                telegram.edit_message(status_chat_id, status_message_id, "❌ Тренд не найден.")
            return {"ok": False, "error": "trend_missing"}

        if take.step_index is not None or take.is_reroll:
            logger.info(
                "generate_take_collection_step",
                extra={
                    "take_id": take_id,
                    "step_index": take.step_index,
                    "is_reroll": take.is_reroll,
                    "session_id": take.session_id,
                },
            )

        input_image_path = None
        if take.session_id:
            from app.models.session import Session as SessionModel
            sess = db.query(SessionModel).filter(SessionModel.id == take.session_id).one_or_none()
            if sess and sess.input_photo_path and os.path.isfile(sess.input_photo_path):
                input_image_path = sess.input_photo_path
        if not input_image_path and take.input_local_paths:
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

        parallel_workers = getattr(settings, "take_generation_parallel_workers", 1)
        parallel_workers = max(1, min(3, int(parallel_workers)))
        max_dim = app_svc.get_take_preview_max_dim()
        watermark_params = app_svc.get_watermark_params(
            getattr(settings, "watermark_text", "NanoBanan Preview")
        )

        if parallel_workers > 1:
            # Параллельная генерация: прогресс-бар обновляется по мере готовности каждого варианта
            def _parallel_progress_text(done: int, total: int = 3) -> str:
                filled = "🟩" * done + "⬜" * (total - done)
                if done == 0:
                    return f"⏳ Генерация снимка [{filled}] Генерируем 3 варианта… 0/{total}"
                if done < total:
                    return f"⏳ Генерация снимка [{filled}] {done}/{total} готово"
                return f"⏳ Генерация снимка [{filled}] Почти готово…"

            if status_chat_id and status_message_id is not None:
                try:
                    telegram.edit_message(
                        status_chat_id, status_message_id, _parallel_progress_text(0)
                    )
                except Exception as e:
                    logger.debug("generate_take_progress_edit_skip", extra={"error": str(e)})

            for v in VARIANTS:
                seeds[v] = random.randint(0, 2**31 - 1)

            done_count = 0
            with ThreadPoolExecutor(max_workers=parallel_workers) as pool:
                futures = {
                    pool.submit(
                        _generate_one_variant,
                        settings=settings,
                        provider_override=app_svc.get_effective_provider(settings),
                        out_dir=out_dir,
                        take_id=take_id,
                        variant=v,
                        seed=seeds[v],
                        prompt_text=prompt_text,
                        model=model,
                        size=size,
                        negative_prompt=negative_prompt,
                        input_image_path=input_image_path,
                        temperature=temperature,
                        image_size_tier=image_size_tier,
                        max_dim=max_dim,
                        watermark_params=watermark_params,
                    ): v
                    for v in VARIANTS
                }
                for fut in as_completed(futures):
                    variant_done = futures[fut]
                    try:
                        v, s, res = fut.result()
                        seeds[v] = s
                        if res:
                            results[v] = res
                        else:
                            failed_variants.append(v)
                    except Exception as e:
                        logger.warning(
                            "generate_take_variant_future_error",
                            extra={"take_id": take_id, "variant": variant_done, "error": str(e)},
                        )
                        failed_variants.append(variant_done)
                    done_count += 1
                    if status_chat_id and status_message_id is not None:
                        try:
                            telegram.edit_message(
                                status_chat_id,
                                status_message_id,
                                _parallel_progress_text(done_count),
                            )
                        except Exception as e:
                            logger.debug(
                                "generate_take_progress_edit_skip",
                                extra={"step": done_count, "error": str(e)},
                            )
        else:
            # Последовательная генерация (как раньше)
            PROGRESS_KEYS = ("progress.take_step_1", "progress.take_step_2", "progress.take_final")
            PROGRESS_DEFAULTS = (
                "⏳ Генерация снимка [🟩⬜⬜] 1/3",
                "⏳ Генерация снимка [🟩🟩⬜] 2/3",
                "⏳ Генерация снимка [🟩🟩🟩] Почти готово…",
            )

            for i, variant in enumerate(VARIANTS):
                if i > 0:
                    time.sleep(RATE_LIMIT_DELAY)

                if status_chat_id and status_message_id is not None:
                    progress_text = runtime_templates.get(PROGRESS_KEYS[i], PROGRESS_DEFAULTS[i])
                    try:
                        telegram.edit_message(status_chat_id, status_message_id, progress_text)
                    except Exception as e:
                        logger.debug("generate_take_progress_edit_skip", extra={"step": i + 1, "error": str(e)})

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
                            image_size_tier=image_size_tier,
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
                        _downscale_and_watermark(
                            original_path,
                            preview_path,
                            max_dim=max_dim,
                            watermark_params=watermark_params,
                        )

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
                "step_index": take.step_index,
                "is_reroll": take.is_reroll,
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
            # Шаблон «баланс + тарифы» после каждой генерации (п. 10 плана SKU ladder)
            try:
                user = db.query(User).filter(User.id == take.user_id).first()
                if user and getattr(user, "telegram_id", None):
                    star_to_rub = getattr(settings, "star_to_rub", 1.3)
                    text, kb = build_balance_tariffs_message(db, user.telegram_id, star_to_rub=star_to_rub)
                    if os.path.exists(MONEY_IMAGE_PATH) and kb:
                        photo_path, is_temp = path_for_telegram_photo(MONEY_IMAGE_PATH)
                        try:
                            telegram.send_photo(
                                status_chat_id,
                                photo_path,
                                caption=text,
                                reply_markup=kb,
                                parse_mode="HTML",
                            )
                        finally:
                            if is_temp and os.path.isfile(photo_path):
                                try:
                                    os.unlink(photo_path)
                                except OSError:
                                    pass
                    else:
                        telegram.send_message(
                            status_chat_id,
                            text,
                            reply_markup=kb,
                            parse_mode="HTML",
                        )
            except Exception as e:
                logger.warning("balance_tariffs_after_generation_failed", extra={"take_id": take_id, "error": str(e)})

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
