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
from datetime import datetime, timezone
from typing import Any

from celery.exceptions import Retry
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.face_asset import FaceAsset
from app.models.take import Take
from app.models.trend import Trend
from app.services.idempotency import IdempotencyStore
from app.services.app_settings.settings_service import AppSettingsService
from app.services.generation_prompt.settings_service import (
    GenerationPromptSettingsService,
    clamp_temperature,
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
from app.services.audit.service import AuditService
from app.services.product_analytics.service import ProductAnalyticsService
from app.services.sessions.service import SessionService
from app.services.takes.service import TakeService
from app.services.users.service import UserService
from app.services.trial_v2.service import TrialV2Service
from app.services.telegram.client import TelegramClient
from app.services.telegram_messages.runtime import runtime_templates

from app.services.trends.service import TrendService
from app.utils.image_formats import aspect_ratio_to_size
from app.services.preview import PreviewService
from app.models.user import User
from app.utils.metrics import (
    takes_created_total,
    takes_completed_total,
    takes_failed_total,
    take_generation_duration_seconds,
    take_previews_ready_total,
    generation_failed_total,
)

logger = logging.getLogger(__name__)

VARIANTS = ["A", "B", "C"]
RATE_LIMIT_DELAY = 1.5
GENERATE_TAKE_LOCK_TTL_SECONDS = 900

# Текст и кнопки после генерации (выбор варианта)
RESULT_CHOOSE_TEXT = (
    "🎉 Ура! Ваши варианты готовы.\n\n"
    "💰 Остался простой шаг —\n"
    "выберите лучший снимок\n"
    "и оплатите его.\n\n"
    "Один снимок — в этом шаге: выберите лучший из трёх.\n\n"
    "✨ После этого вы получите фото\n"
    "в полном качестве\n"
    "для соцсетей без надписей."
)
RESULT_CHOOSE_BUTTON_LABEL = "💎 Выбрать и оплатить {}"  # .format("A") -> "💎 Выбрать и оплатить A"
RESULT_CHOOSE_TEXT_WITH_PACK = (
    "🎉 Ваши фото готовы\n\n"
    "Выберите лучший вариант — он будет сохранён\n\n"
    "Или получите все 3 фото сразу\n"
    "в максимальном качестве и без водяных знаков"
)
RESULT_CHOOSE_BUTTON_LABEL_PACK = "💎 Выбрать вариант {}"  # без «оплатить»
MAX_VARIANT_RETRIES = 2
VARIANT_RETRY_DELAY = 2.0

# Температуры для 3 вариантов в флоу «Сделать такую же» (в пределах MAX_PRODUCTION_TEMPERATURE=0.5)
COPY_VARIANT_TEMPERATURES = {"A": 0.2, "B": 0.35, "C": 0.5}

# Reply-клавиатура (меню внизу чата), совпадает с main_menu_keyboard в боте
MAIN_MENU_REPLY = {
    "keyboard": [
        [{"text": "🔥 Создать фото"}, {"text": "🔄 Сделать такую же"}],
        [{"text": "🧩 Соединить фото"}, {"text": "🛒 Купить пакет"}],
        [{"text": "👤 Мой профиль"}],
    ],
    "resize_keyboard": True,
}


def _build_prompt_for_take(db: Session, take: Take, trend: Trend) -> tuple[str, str | None, str, str, str | None]:
    """Build prompt from trend + master settings. Returns (prompt, negative, model, size, image_size_tier)."""
    gs = GenerationPromptSettingsService(db)
    effective = gs.get_effective(profile="release")
    model = effective.get("default_model", "gemini-2.5-flash-image")
    # Приоритет: выбор пользователя (take.image_size), иначе дефолт из админки (default_aspect_ratio → size)
    size = take.image_size or aspect_ratio_to_size(effective.get("default_aspect_ratio", "1:1"))
    image_size_tier = (getattr(trend, "prompt_image_size_tier", None) or "").strip() or effective.get("default_image_size_tier") or "4K"

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
    if trend.prompt_model:
        model = trend.prompt_model
    negative = None
    return prompt_text, negative, model, size, image_size_tier


def _resolve_generation_config(
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
    base_seed = normalize_seed(trend_seed if trend_seed is not None else effective_release.get("default_seed"))

    return {
        "aspect_ratio": aspect_ratio,
        "top_p": top_p,
        "candidate_count": 1,  # Production flow is always single candidate.
        "media_resolution": media_resolution,
        "thinking_config": thinking_config,
        "base_seed": base_seed,
    }


def _build_take_variant_seeds(base_seed: int | None) -> dict[str, int]:
    if base_seed is not None:
        return {"A": base_seed, "B": base_seed + 1, "C": base_seed + 2}
    return {v: random.randint(0, 2**31 - 1) for v in VARIANTS}


def _resolve_take_variant_sampling(
    *,
    take_type: str | None,
    trend: Trend | None,
    effective_release: dict[str, Any],
    base_temperature: float | None,
    base_top_p: float | None,
) -> dict[str, dict[str, float | None]]:
    out: dict[str, dict[str, float | None]] = {
        variant: {"temperature": base_temperature, "top_p": base_top_p}
        for variant in VARIANTS
    }

    if take_type == "COPY":
        for variant in VARIANTS:
            out[variant]["temperature"] = COPY_VARIANT_TEMPERATURES.get(variant, base_temperature)
        return out

    if take_type != "TREND":
        return out

    trend_temperature = getattr(trend, "prompt_temperature", None) if trend is not None else None
    trend_top_p = getattr(trend, "prompt_top_p", None) if trend is not None else None

    if trend_temperature is None:
        for variant in VARIANTS:
            key = f"default_temperature_{variant.lower()}"
            specific = effective_release.get(key)
            out[variant]["temperature"] = (
                clamp_temperature(specific, default=0.7) if specific not in (None, "") else base_temperature
            )

    if trend_top_p is None:
        for variant in VARIANTS:
            key = f"default_top_p_{variant.lower()}"
            specific = effective_release.get(key)
            clamped = clamp_top_p(specific)
            out[variant]["top_p"] = clamped if clamped is not None else base_top_p

    return out


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
    aspect_ratio: str | None,
    top_p: float | None,
    candidate_count: int,
    media_resolution: str | None,
    thinking_config: dict[str, Any] | None,
) -> tuple[str, int, dict | None]:
    """
    Сгенерировать один вариант (A/B/C) в потоке. Возвращает (variant, seed, result_dict) или (variant, seed, None) при ошибке.
    Создаёт свой экземпляр провайдера в потоке (thread-safe). Превью строит через PreviewService (отдельная сессия БД в потоке).
    """
    ext = "png"
    original_path = os.path.join(out_dir, f"{take_id}_{variant}_original.{ext}")
    preview_path_placeholder = os.path.join(out_dir, f"{take_id}_{variant}_preview.{ext}")
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
                aspect_ratio=aspect_ratio,
                top_p=top_p,
                candidate_count=candidate_count,
                media_resolution=media_resolution,
                thinking_config=thinking_config,
            )
            result = generate_with_retry(
                provider,
                req,
                settings,
                model_version=model,
                safety_settings_snapshot=getattr(settings, "gemini_safety_settings", None),
                streaming_enabled=False,
                provider_name=provider_override or "gemini",
            )
            with open(original_path, "wb") as f:
                f.write(result.image_content)
            db_thread = SessionLocal()
            try:
                preview_path = PreviewService.build_preview(
                    original_path,
                    preview_path_placeholder,
                    "take",
                    db=db_thread,
                )
            finally:
                db_thread.close()
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


# Коды ошибок, при которых возвращаем бесплатный снимок (только серверные сбои; не возвращаем при вине пользователя/окружения)
_REFUND_FREE_TAKE_ERROR_CODES = frozenset({"all_variants_failed", "unexpected_error"})


def _refund_free_take_on_failure(db, take, error_code: str | None = None) -> None:
    """
    При ошибке генерации вернуть бесплатный снимок, если take использовал сессию free_preview.
    Возврат только при серверных ошибках (all_variants_failed, unexpected_error), чтобы исключить
    абуз: пользователь удаляет файл → identity_image_missing → не возвращаем.
    """
    if not take or not take.session_id:
        return
    if error_code not in _REFUND_FREE_TAKE_ERROR_CODES:
        return
    from app.models.session import Session as SessionModel
    sess = db.query(SessionModel).filter(SessionModel.id == take.session_id).one_or_none()
    if not sess:
        return
    if getattr(sess, "pack_id", None) == "free_preview":
        UserService(db).return_free_take(take.user_id)
        return
    # Для платных пакетов возвращаем слот генерации при серверной ошибке.
    try:
        SessionService(db).return_take(sess)
    except Exception:
        logger.exception("refund_paid_take_failed", extra={"take_id": getattr(take, "id", None), "session_id": getattr(sess, "id", None)})


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
    intro_message_id: int | None = None,
) -> dict:
    """Generate 3 preview variants (A/B/C) for a Take."""
    db: Session = SessionLocal()
    telegram = TelegramClient()
    started_at = time.time()
    lock_store = None
    lock_key = f"take:generate:{take_id}"
    lock_acquired = False
    try:
        take_svc = TakeService(db)
        session_svc = SessionService(db)

        take = take_svc.get_take(take_id)
        if not take:
            logger.error("generate_take_not_found", extra={"take_id": take_id})
            if status_chat_id and status_message_id:
                telegram.edit_message(status_chat_id, status_message_id, "❌ Задача не найдена.")
            return {"ok": False, "error": "take_not_found"}

        if take.status in {"ready", "partial_fail", "failed"}:
            logger.info("generate_take_skip_terminal", extra={"take_id": take_id, "status": take.status})
            return {"ok": True, "take_id": take_id, "status": take.status, "skipped": "terminal"}

        try:
            lock_store = IdempotencyStore()
            lock_acquired = lock_store.check_and_set(lock_key, ttl_seconds=GENERATE_TAKE_LOCK_TTL_SECONDS)
        except Exception as e:
            logger.warning("generate_take_lock_unavailable", extra={"take_id": take_id, "error": str(e)})
            # Fail open: generation must still work if Redis is temporarily unavailable.
            lock_store = None
            lock_acquired = True

        if not lock_acquired:
            logger.info("generate_take_skip_in_progress", extra={"take_id": take_id})
            retry_count = int(getattr(getattr(self, "request", None), "retries", 0) or 0)
            max_retries = 60
            if retry_count < max_retries:
                raise self.retry(countdown=15, max_retries=max_retries)
            logger.warning("generate_take_in_progress_retry_exhausted", extra={"take_id": take_id, "retries": retry_count})
            return {"ok": False, "take_id": take_id, "status": take.status, "error": "in_progress_timeout"}

        db.refresh(take)
        if take.status in {"ready", "partial_fail", "failed"}:
            logger.info("generate_take_skip_terminal_after_lock", extra={"take_id": take_id, "status": take.status})
            return {"ok": True, "take_id": take_id, "status": take.status, "skipped": "terminal"}

        takes_created_total.inc()

        trend_svc = TrendService(db)
        trend = trend_svc.get(take.trend_id) if take.trend_id else None

        gs_release = GenerationPromptSettingsService(db)
        effective_release = gs_release.get_effective(profile="release")

        if take.take_type == "COPY":
            if not (take.custom_prompt or "").strip():
                logger.error("generate_take_copy_no_prompt", extra={"take_id": take_id})
                take_svc.set_status(take, "failed", error_code="copy_prompt_missing")
                _refund_free_take_on_failure(db, take, "copy_prompt_missing")
                takes_failed_total.inc()
                generation_failed_total.labels(error_code="copy_prompt_missing", source="take").inc()
                ProductAnalyticsService(db).track(
                    "generation_failed",
                    take.user_id,
                    take_id=take_id,
                    session_id=take.session_id,
                    trend_id=take.trend_id,
                    properties={"error_code": "copy_prompt_missing", "latency_ms": int((time.time() - started_at) * 1000)},
                )
                db.commit()
                if status_chat_id and status_message_id:
                    telegram.edit_message(status_chat_id, status_message_id, "❌ Не получен промпт от анализа. Начните заново: «🔄 Сделать такую же».")
                return {"ok": False, "error": "copy_prompt_missing"}
            prompt_text = take.custom_prompt.strip()
            negative_prompt = None
            model = effective_release.get("default_model", "gemini-2.5-flash-image")
            size = take.image_size or aspect_ratio_to_size(effective_release.get("default_aspect_ratio", "1:1"))
            image_size_tier = effective_release.get("default_image_size_tier") or "4K"
        elif take.take_type == "CUSTOM" and take.custom_prompt:
            prompt_text = take.custom_prompt
            negative_prompt = None
            model = effective_release.get("default_model", "gemini-2.5-flash-image")
            size = take.image_size or aspect_ratio_to_size(effective_release.get("default_aspect_ratio", "1:1"))
            image_size_tier = effective_release.get("default_image_size_tier") or "4K"
        elif trend:
            prompt_text, negative_prompt, model, size, image_size_tier = _build_prompt_for_take(db, take, trend)
        else:
            logger.error("generate_take_no_trend", extra={"take_id": take_id})
            take_svc.set_status(take, "failed", error_code="trend_missing")
            _refund_free_take_on_failure(db, take, "trend_missing")
            takes_failed_total.inc()
            generation_failed_total.labels(error_code="trend_missing", source="take").inc()
            ProductAnalyticsService(db).track(
                "generation_failed",
                take.user_id,
                take_id=take_id,
                session_id=take.session_id,
                trend_id=take.trend_id,
                properties={"error_code": "trend_missing", "latency_ms": int((time.time() - started_at) * 1000)},
            )
            db.commit()
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
        face_asset = None
        if getattr(take, "face_asset_id", None):
            face_asset = db.query(FaceAsset).filter(FaceAsset.id == take.face_asset_id).one_or_none()
            if face_asset and face_asset.status == "failed_multi_face":
                logger.error("generate_take_face_asset_multi_face", extra={"take_id": take_id, "face_asset_id": face_asset.id})
                take_svc.set_status(take, "failed", error_code="face_asset_multi_face")
                _refund_free_take_on_failure(db, take, "face_asset_multi_face")
                takes_failed_total.inc()
                generation_failed_total.labels(error_code="face_asset_multi_face", source="take").inc()
                ProductAnalyticsService(db).track(
                    "generation_failed",
                    take.user_id,
                    take_id=take_id,
                    session_id=take.session_id,
                    trend_id=take.trend_id,
                    properties={"error_code": "face_asset_multi_face", "latency_ms": int((time.time() - started_at) * 1000)},
                )
                db.commit()
                if status_chat_id and status_message_id:
                    telegram.edit_message(status_chat_id, status_message_id, "❌ На фото несколько лиц. Загрузите селфи с одним человеком.")
                return {"ok": False, "error": "face_asset_multi_face"}
            if face_asset and face_asset.selected_path and os.path.isfile(face_asset.selected_path):
                input_image_path = face_asset.selected_path
        if (not input_image_path) and take.session_id:
            from app.models.session import Session as SessionModel
            sess = db.query(SessionModel).filter(SessionModel.id == take.session_id).one_or_none()
            if sess and sess.input_photo_path and os.path.isfile(sess.input_photo_path):
                input_image_path = sess.input_photo_path
        if not input_image_path and take.input_local_paths:
            candidate = take.input_local_paths[0] if isinstance(take.input_local_paths[0], str) else None
            if candidate and os.path.isfile(candidate):
                input_image_path = candidate

        if take.take_type == "COPY" and not input_image_path:
            logger.error("generate_take_copy_missing_identity", extra={"take_id": take_id})
            take_svc.set_status(take, "failed", error_code="identity_image_missing")
            _refund_free_take_on_failure(db, take, "identity_image_missing")
            takes_failed_total.inc()
            generation_failed_total.labels(error_code="identity_image_missing", source="take").inc()
            ProductAnalyticsService(db).track(
                "generation_failed",
                take.user_id,
                take_id=take_id,
                session_id=take.session_id,
                trend_id=take.trend_id,
                properties={"error_code": "identity_image_missing", "latency_ms": int((time.time() - started_at) * 1000)},
            )
            db.commit()
            if status_chat_id and status_message_id:
                telegram.edit_message(status_chat_id, status_message_id, "❌ Не найден файл с фото. Начните заново: «🔄 Сделать такую же».")
            return {"ok": False, "error": "identity_image_missing"}

        if take.take_type == "TREND" and trend and not input_image_path:
            logger.error("generate_take_trend_missing_input", extra={"take_id": take_id})
            take_svc.set_status(take, "failed", error_code="input_image_missing")
            _refund_free_take_on_failure(db, take, "input_image_missing")
            takes_failed_total.inc()
            generation_failed_total.labels(error_code="input_image_missing", source="take").inc()
            ProductAnalyticsService(db).track(
                "generation_failed",
                take.user_id,
                take_id=take_id,
                session_id=take.session_id,
                trend_id=take.trend_id,
                properties={"error_code": "input_image_missing", "latency_ms": int((time.time() - started_at) * 1000)},
            )
            db.commit()
            if status_chat_id and status_message_id:
                telegram.edit_message(status_chat_id, status_message_id, "❌ Исходное фото недоступно. Начните заново с «Создать фото».")
            return {"ok": False, "error": "input_image_missing"}

        temperature = trend.prompt_temperature if (trend and trend.prompt_temperature is not None) else effective_release.get("default_temperature")

        # Aspect ratio source of truth for production:
        # 1) trend.prompt_aspect_ratio, 2) user-selected take.image_size, 3) master default_aspect_ratio.
        prefer_size_aspect_ratio = bool((take.image_size or "").strip())
        resolved_generation_cfg = _resolve_generation_config(
            trend=trend,
            effective_release=effective_release,
            model=model,
            size=size,
            prefer_size_aspect_ratio=prefer_size_aspect_ratio,
        )
        base_seed = resolved_generation_cfg["base_seed"]
        variant_sampling = _resolve_take_variant_sampling(
            take_type=take.take_type,
            trend=trend,
            effective_release=effective_release,
            base_temperature=temperature,
            base_top_p=resolved_generation_cfg["top_p"],
        )

        app_svc = AppSettingsService(db)
        provider_override = app_svc.get_effective_provider(settings)
        provider_name = provider_override or getattr(settings, "image_provider", "gemini")
        provider = ImageProviderFactory.create_from_settings(settings, provider_name)
        ProductAnalyticsService(db).track(
            "generation_started",
            take.user_id,
            take_id=take_id,
            session_id=take.session_id,
            trend_id=take.trend_id,
            properties={"model": model, "provider": provider_name},
        )

        out_dir = os.path.join(settings.storage_base_path, "outputs")
        os.makedirs(out_dir, exist_ok=True)

        results = {}
        seeds = _build_take_variant_seeds(base_seed)
        failed_variants = []

        parallel_workers = getattr(settings, "take_generation_parallel_workers", 1)
        parallel_workers = max(1, min(3, int(parallel_workers)))

        if parallel_workers > 1:
            # Параллельная генерация: прогресс-бар обновляется по мере готовности каждого варианта
            def _parallel_progress_text(done: int, total: int = 3) -> str:
                filled = "🟩" * done + "⬜" * (total - done)
                if done == 0:
                    return runtime_templates.get(
                        "progress.take_parallel",
                        f"⏳ Анализируем фото [{filled}]\nСоздаём варианты · 1 из {total}",
                    )
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
                        temperature=variant_sampling[v]["temperature"],
                        image_size_tier=image_size_tier,
                        aspect_ratio=resolved_generation_cfg["aspect_ratio"],
                        top_p=variant_sampling[v]["top_p"],
                        candidate_count=resolved_generation_cfg["candidate_count"],
                        media_resolution=resolved_generation_cfg["media_resolution"],
                        thinking_config=resolved_generation_cfg["thinking_config"],
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

                seed = seeds[variant]
                seeds[variant] = seed

                req_temperature = variant_sampling[variant]["temperature"]
                req_top_p = variant_sampling[variant]["top_p"]
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
                            temperature=req_temperature,
                            seed=seed,
                            image_size_tier=image_size_tier,
                            aspect_ratio=resolved_generation_cfg["aspect_ratio"],
                            top_p=req_top_p,
                            candidate_count=resolved_generation_cfg["candidate_count"],
                            media_resolution=resolved_generation_cfg["media_resolution"],
                            thinking_config=resolved_generation_cfg["thinking_config"],
                        )
                        result = generate_with_retry(
                            provider,
                            req,
                            settings,
                            model_version=model,
                            safety_settings_snapshot=getattr(settings, "gemini_safety_settings", None),
                            streaming_enabled=False,
                            provider_name=provider_name,
                        )

                        ext = "png"
                        original_path = os.path.join(out_dir, f"{take_id}_{variant}_original.{ext}")
                        with open(original_path, "wb") as f:
                            f.write(result.image_content)

                        preview_path_placeholder = os.path.join(out_dir, f"{take_id}_{variant}_preview.{ext}")
                        preview_path = PreviewService.build_preview(
                            original_path,
                            preview_path_placeholder,
                            "take",
                            db=db,
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
            _refund_free_take_on_failure(db, take, "all_variants_failed")
            takes_failed_total.inc()
            generation_failed_total.labels(error_code="all_variants_failed", source="take").inc()
            ProductAnalyticsService(db).track(
                "generation_failed",
                take.user_id,
                take_id=take_id,
                session_id=take.session_id,
                trend_id=take.trend_id,
                properties={"error_code": "all_variants_failed", "latency_ms": int((time.time() - started_at) * 1000)},
            )
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
                telegram.send_message(status_chat_id, "Попробуйте ещё раз или вернитесь в меню.", reply_markup=keyboard)
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

        takes_completed_total.inc()
        take_previews_ready_total.inc()
        generation_duration_sec = (
            (datetime.now(timezone.utc) - take.created_at).total_seconds()
            if take.created_at else (time.time() - started_at)
        )
        if generation_duration_sec >= 0:
            take_generation_duration_seconds.observe(generation_duration_sec)

        # Не списываем лимит на этапе превью:
        # расход идёт только при фактической выдаче full-quality (4K).

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
        generation_latency_ms = (
            int((datetime.now(timezone.utc) - take.created_at).total_seconds() * 1000)
            if take.created_at else None
        )
        # Duplicate events possible on Celery retry; see docs/TELEMETRY_PRODUCT_EVENTS_RETRY_RISK.md
        analytics = ProductAnalyticsService(db)
        analytics.track_funnel_step(
            "take_preview_ready",
            take.user_id,
            session_id=take.session_id,
            trend_id=take.trend_id,
            take_id=take_id,
            source_component="worker.generate_take",
            properties={
                "preview_count": len(results),
                "generation_latency_ms": generation_latency_ms,
            },
        )
        if take.trend_id:
            analytics.track(
                "trend_preview_ready",
                take.user_id,
                session_id=take.session_id,
                trend_id=take.trend_id,
                take_id=take_id,
                source_component="worker.generate_take",
                properties={
                    "preview_count": len(results),
                    "generation_latency_ms": generation_latency_ms,
                },
            )
        latency_ms = int((time.time() - started_at) * 1000)
        analytics.track(
            "generation_completed",
            take.user_id,
            take_id=take_id,
            session_id=take.session_id,
            trend_id=take.trend_id,
            source_component="worker.generate_take",
            properties={"model": model, "provider": provider_name, "latency_ms": latency_ms},
        )

        reward_push_payload = None
        should_process_trial_referral = (
            status == "ready"
            and len(results) == 3
            and str(getattr(take, "take_type", "") or "").upper() != "COPY"
        )
        if should_process_trial_referral:
            try:
                with db.begin_nested():
                    reward_push_payload = TrialV2Service(db).process_first_successful_preview(take.user_id)
                    if reward_push_payload:
                        analytics.track(
                            "trial_referral_reward_earned",
                            reward_push_payload["referrer_user_id"],
                            take_id=take_id,
                            source_component="worker.generate_take",
                            properties={"referral_user_id": take.user_id},
                        )
            except Exception:
                logger.exception("trial_referral_reward_process_failed", extra={"take_id": take_id, "user_id": take.user_id})

        db.commit()

        if status_chat_id:
            if status_message_id:
                try:
                    telegram.delete_message(status_chat_id, status_message_id)
                except Exception:
                    pass
            if intro_message_id:
                try:
                    telegram.delete_message(status_chat_id, intro_message_id)
                except Exception:
                    pass

            # Платным считаем любой пакет, кроме free_preview.
            # Для платных отправляем сразу оригиналы (без watermark, без сжатия).
            has_active_paid_package = False
            paid_session = None
            if take.session_id:
                session = session_svc.get_session(take.session_id)
                if session and (session.pack_id or "").strip().lower() != "free_preview":
                    has_active_paid_package = True
                    paid_session = session
            if not has_active_paid_package and take.user_id:
                active = session_svc.get_active_session(take.user_id)
                if active and (active.pack_id or "").strip().lower() != "free_preview":
                    has_active_paid_package = True
                    paid_session = active
            media = []
            available_variants = []
            for variant in VARIANTS:
                if variant not in results:
                    continue
                media_path = results[variant]["original"] if has_active_paid_package else results[variant]["preview"]
                media_type = "document" if has_active_paid_package else "photo"
                media.append({
                    "type": media_type,
                    "media_path": media_path,
                    "caption": variant,
                })
                available_variants.append(variant)

            if media:
                try:
                    if len(media) == 1:
                        if has_active_paid_package:
                            telegram.send_document(
                                status_chat_id,
                                media[0]["media_path"],
                                caption=f"Вариант {media[0].get('caption') or ''}".strip(),
                            )
                        else:
                            telegram.send_photo(
                                status_chat_id,
                                media[0]["media_path"],
                                caption=media[0].get("caption") or "",
                            )
                    else:
                        telegram.send_media_group(status_chat_id, media)
                except Exception as e:
                    logger.exception("generate_take_send_photo_failed", extra={"take_id": take_id})
                    telegram.send_message(status_chat_id, f"✅ Фото готово, но не удалось отправить: {e}")

            trial_v2_mode = False
            if not has_active_paid_package and take.user_id:
                trial_user = db.query(User).filter(User.id == take.user_id).one_or_none()
                trial_v2_mode = bool(trial_user and getattr(trial_user, "trial_v2_eligible", False))

            if trial_v2_mode:
                result_text = (
                    "✨ Готово! Посмотри, что получилось — выбери вариант:"
                )
                idx_map = {"A": "1", "B": "2", "C": "3"}
                label_map = {"A": "1️⃣ Выбрать первый вариант", "B": "2️⃣ Выбрать второй вариант", "C": "3️⃣ Выбрать третий вариант"}
                choose_buttons = [
                    {"text": label_map.get(v, f"{idx_map.get(v, v)}️⃣ Выбрать вариант"), "callback_data": f"trial_select:{take_id}:{v}"}
                    for v in available_variants
                ]
                keyboard_rows = [[btn] for btn in choose_buttons]
                if len(available_variants) == 3:
                    keyboard_rows.append([{"text": "🤍 Выбрать все 3", "callback_data": f"trial_select:{take_id}:ALL"}])
            else:
                if has_active_paid_package and paid_session:
                    remaining = max(0, int((paid_session.takes_limit or 0) - (paid_session.takes_used or 0)))
                    result_text = (
                        f"Осталось {remaining} фото для создания образов\n\n"
                        f"{RESULT_CHOOSE_TEXT_WITH_PACK}"
                    )
                else:
                    result_text = RESULT_CHOOSE_TEXT_WITH_PACK if has_active_paid_package else RESULT_CHOOSE_TEXT
                button_label_tpl = RESULT_CHOOSE_BUTTON_LABEL_PACK if has_active_paid_package else RESULT_CHOOSE_BUTTON_LABEL
                choose_buttons = [
                    {"text": button_label_tpl.format(v), "callback_data": f"choose:{take_id}:{v}"}
                    for v in available_variants
                ]
                keyboard_rows = [[btn] for btn in choose_buttons]
                if has_active_paid_package:
                    keyboard_rows.append([{"text": "📦 Вернуть все 3 в лучшем качестве", "callback_data": f"return_all_hq:{take_id}"}])

            keyboard_rows.append([{"text": "🔁 Все 3 не подходят", "callback_data": f"rescue:reject_set:{take_id}"}])
            keyboard = {"inline_keyboard": keyboard_rows}
            telegram.send_message(
                status_chat_id,
                result_text,
                reply_markup=keyboard,
            )

        if reward_push_payload:
            try:
                telegram.send_message(
                    str(reward_push_payload["referrer_telegram_id"]),
                    "🎉 Вы получили 1 фото в полном качестве за приглашённого друга.\n\n"
                    "Теперь вы можете забрать выбранный результат бесплатно и без водяных знаков.",
                    reply_markup={"inline_keyboard": [[{"text": "⬇️ Забрать фото", "callback_data": "trial_claim:next"}]]},
                )
            except Exception:
                logger.exception(
                    "trial_referral_reward_push_failed",
                    extra={"referrer_telegram_id": reward_push_payload.get("referrer_telegram_id")},
                )

        return {"ok": True, "take_id": take_id, "status": status, "variants": list(results.keys())}
    except Retry:
        raise
    except Exception:
        logger.exception("generate_take_fatal", extra={"take_id": take_id})
        generation_failed_total.labels(error_code="unexpected_error", source="take").inc()
        try:
            take = take_svc.get_take(take_id)
            if take and take.status == "generating":
                take_svc.set_status(take, "failed", error_code="unexpected_error")
                _refund_free_take_on_failure(db, take, "unexpected_error")
                takes_failed_total.inc()
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
        if lock_store is not None and lock_acquired:
            try:
                lock_store.release(lock_key)
            except Exception as e:
                logger.warning("generate_take_lock_release_failed", extra={"take_id": take_id, "error": str(e)})
        db.close()
        telegram.close()
