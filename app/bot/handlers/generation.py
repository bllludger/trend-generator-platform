"""Handlers for generation flow: format selection, job creation, regeneration."""
import asyncio
import logging
import os
from typing import Any
from uuid import uuid4
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from app.bot.states import BotStates
from app.bot.helpers import t, tr, get_db_session, _try_delete_messages, logger
from app.bot.keyboards import main_menu_keyboard
from app.bot.constants import (
    IMAGE_FORMATS, TREND_CUSTOM_ID, DEFAULT_ASPECT_RATIO,
    GENERATION_INTRO_IMAGE_PATH, GENERATION_INTRO_TEXT,
    GENERATION_INTRO_IMAGE_PATH_WOMEN, GENERATION_INTRO_IMAGE_PATH_MEN, GENERATION_INTRO_IMAGE_PATH_COUPLES,
    MONEY_IMAGE_PATH,
)
from app.core.config import settings
from app.constants import AUDIENCE_WOMEN, AUDIENCE_MEN, AUDIENCE_COUPLES
from app.services.users.service import UserService
from app.services.trends.service import TrendService
from app.services.takes.service import TakeService
from app.services.sessions.service import SessionService
from app.services.jobs.service import JobService
from app.services.audit.service import AuditService
from app.services.product_analytics.service import ProductAnalyticsService
from app.services.security.settings_service import SecuritySettingsService
from app.services.face_id.asset_service import FaceAssetService
from app.services.idempotency import IdempotencyStore
from app.services.trial_v2.service import TrialV2Service
from app.services.compensations.service import CompensationService
from app.models.user import User
from app.models.take import Take as TakeModel
from app.utils.metrics import jobs_created_total, balance_rejected_total, face_id_pending_takes
from app.utils.telegram_photo import path_for_telegram_photo

generation_router = Router()


def _generation_intro_image_path_for_audience(audience: str) -> str:
    audience_norm = (audience or "").strip().lower()
    if audience_norm == AUDIENCE_MEN:
        return GENERATION_INTRO_IMAGE_PATH_MEN
    if audience_norm == AUDIENCE_COUPLES:
        return GENERATION_INTRO_IMAGE_PATH_COUPLES
    if audience_norm == AUDIENCE_WOMEN:
        return GENERATION_INTRO_IMAGE_PATH_WOMEN
    return GENERATION_INTRO_IMAGE_PATH


async def _send_packages_upsell(bot: Bot, chat_id: int, reason_text: str | None = None) -> None:
    """Показать баннер покупки пакетов, когда бесплатный/Trial лимит исчерпан."""
    text = (
        "🎁 Бесплатный лимит закончился.\n\n"
        f"{(reason_text or 'Чтобы продолжить, выберите пакет.').strip()}\n\n"
        "Откройте тарифы и получите фото без водяного знака."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Открыть тарифы", callback_data="shop:open")],
        [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
    ])
    if os.path.exists(MONEY_IMAGE_PATH):
        try:
            photo_path, is_temp = path_for_telegram_photo(MONEY_IMAGE_PATH)
            await bot.send_photo(chat_id, photo=FSInputFile(photo_path), caption=text, reply_markup=kb)
            if is_temp and os.path.isfile(photo_path):
                try:
                    os.unlink(photo_path)
                except OSError:
                    pass
            return
        except Exception:
            logger.exception("packages_upsell_photo_failed")
    await bot.send_message(chat_id, text, reply_markup=kb)


def _sanitize_enqueue_error_reason(err: str | None) -> str | None:
    if not err:
        return None
    compact = " ".join(str(err).split())
    if not compact:
        return None
    return compact[:500]


def _mark_take_enqueue_failed(
    take_id: str,
    *,
    actor_id: str | None = None,
    reason: str | None = None,
) -> None:
    """Mark take as failed when Celery enqueue did not happen, with compensation for free preview."""
    with get_db_session() as db:
        take_svc = TakeService(db)
        session_svc = SessionService(db)
        take = take_svc.get_take(take_id)
        if not take:
            return
        error_code = "enqueue_failed"
        reason_norm = (reason or "").strip().lower()
        if "failed_multi_face" in reason_norm or "multi_face" in reason_norm:
            error_code = "face_asset_multi_face"
        elif "failed_error" in reason_norm or "face_id" in reason_norm:
            error_code = "face_asset_failed_error"
        if take.status in {"generating", "awaiting_face_id"}:
            take_svc.set_status(take, "failed", error_code=error_code)
        reason_sanitized = _sanitize_enqueue_error_reason(reason)
        audit_payload: dict[str, Any] = {"session_id": take.session_id, "error_code": error_code}
        if reason_sanitized:
            audit_payload["enqueue_error"] = reason_sanitized
        try:
            AuditService(db).log(
                actor_type="system",
                actor_id=actor_id or "bot",
                action="take_enqueue_failed",
                entity_type="take",
                entity_id=take_id,
                payload=audit_payload,
            )
        except Exception:
            logger.exception("take_enqueue_failed_audit_error", extra={"take_id": take_id})

        if take.session_id:
            session = session_svc.get_session(take.session_id)
            if session and str(session.pack_id or "").strip().lower() == "free_preview":
                user = db.query(User).filter(User.id == take.user_id).one_or_none()
                if user and bool(getattr(user, "trial_v2_eligible", False)):
                    trend_key = take.trend_id or (TREND_CUSTOM_ID if take.take_type == "CUSTOM" else None)
                    if trend_key:
                        try:
                            TrialV2Service(db).rollback_take_started(
                                user_id=take.user_id,
                                trend_id=trend_key,
                                take_id=take.id,
                            )
                        except Exception:
                            logger.exception("take_enqueue_failed_trial_rollback_error", extra={"take_id": take_id})
                elif not bool(getattr(take, "is_reroll", False)) and not bool(getattr(take, "is_rescue_photo_replace", False)):
                    try:
                        UserService(db).return_free_take(take.user_id)
                    except Exception:
                        logger.exception("take_enqueue_failed_refund_error", extra={"take_id": take_id})
            elif session and str(session.pack_id or "").strip().lower() != "free_preview":
                try:
                    session_svc.return_take(session)
                except Exception:
                    logger.exception("take_enqueue_failed_paid_return_error", extra={"take_id": take_id, "session_id": take.session_id})
        try:
            face_id_pending_takes.set(int(db.query(TakeModel.id).filter(TakeModel.status == "awaiting_face_id").count()))
        except Exception:
            logger.exception("take_enqueue_failed_pending_gauge_error", extra={"take_id": take_id})

        try:
            ProductAnalyticsService(db).track(
                "generation_failed",
                take.user_id,
                take_id=take_id,
                session_id=take.session_id,
                trend_id=take.trend_id,
                properties={"error_code": error_code},
            )
        except Exception:
            logger.exception("take_enqueue_failed_analytics_error", extra={"take_id": take_id})


# --- Step 3: Create job and start generation (format step disabled, always 4:3) ---
async def _create_job_and_start_generation(
    *,
    bot: Bot,
    state: FSMContext,
    format_key: str,
    chat_id: int,
    message_ids_to_delete: int | list | None,
    from_user: Any,
    answer_alert: Any,
    send_progress_to_chat_id: int,
) -> bool:
    """Создать take и запустить генерацию. Возвращает True при успехе, False при ошибке (answer_alert уже вызван)."""
    telegram_id = str(from_user.id)
    data = await state.get_data()
    photo_file_id = data.get("photo_file_id")
    photo_local_path = data.get("photo_local_path")
    trend_id = data.get("selected_trend_id")
    custom_prompt = data.get("custom_prompt")
    state_face_asset_id = data.get("face_asset_id")

    if not photo_file_id or not photo_local_path:
        await answer_alert(t("errors.session_expired_photo", "Сессия истекла. Начните заново: отправьте фото."), show_alert=True)
        await state.clear()
        return False
    input_file_ids = [photo_file_id]
    input_local_paths = [photo_local_path]
    if not trend_id:
        await answer_alert(t("errors.choose_trend_or_idea", "Выберите тренд или введите свою идею."), show_alert=True)
        return False
    if trend_id == TREND_CUSTOM_ID and not custom_prompt:
        await answer_alert(t("errors.enter_idea", "Введите описание своей идеи."), show_alert=True)
        return False
    for path in input_local_paths:
        if os.path.exists(path):
            size_mb = os.path.getsize(path) / (1024 * 1024)
            if size_mb > settings.max_file_size_mb:
                await answer_alert(
                    tr("errors.file_too_large_max", "Файл слишком большой ({size_mb:.1f} МБ). Максимум {max_mb} МБ.", size_mb=size_mb, max_mb=settings.max_file_size_mb),
                    show_alert=True,
                )
                return False
    image_size = IMAGE_FORMATS[format_key]
    _mid = message_ids_to_delete if isinstance(message_ids_to_delete, int) else (message_ids_to_delete[0] if message_ids_to_delete else 0)
    idempotency_key = f"job:{chat_id}:{_mid}:{format_key}"
    if not IdempotencyStore().check_and_set(idempotency_key):
        await answer_alert(t("errors.request_processing", "⏳ Запрос уже обрабатывается."))
        return False
    created_take_id: str | None = None
    enqueued = False
    awaiting_face_asset = False
    is_paid_active_flow = False
    audience = (data.get("audience_type") or "").strip().lower() or AUDIENCE_WOMEN
    try:
        with get_db_session() as db:
            user_service = UserService(db)
            trend_service = TrendService(db)
            take_svc = TakeService(db)
            session_svc = SessionService(db)
            audit = AuditService(db)
            user = user_service.get_or_create_user(
                telegram_id,
                telegram_username=getattr(from_user, "username", None),
                telegram_first_name=getattr(from_user, "first_name", None),
                telegram_last_name=getattr(from_user, "last_name", None),
            )
            if trend_id != TREND_CUSTOM_ID:
                trend = trend_service.get(trend_id)
                if not trend or not trend.enabled:
                    await answer_alert(t("errors.trend_unavailable", "Тренд недоступен."), show_alert=True)
                    return False
            is_copy_flow = bool(data.get("copy_flow_origin"))
            take_type = "COPY" if is_copy_flow else ("CUSTOM" if trend_id == TREND_CUSTOM_ID else "TREND")
            copy_ref = data.get("reference_path") if is_copy_flow else None
            face_asset = None
            if (not is_copy_flow) and isinstance(state_face_asset_id, str) and state_face_asset_id.strip():
                face_asset = FaceAssetService(db).get(state_face_asset_id.strip())
                if face_asset and str(face_asset.user_id) != str(user.id):
                    face_asset = None
                if face_asset and face_asset.status == "failed_multi_face":
                    await answer_alert(
                        "❌ На фото несколько лиц. Загрузите селфи с одним человеком.",
                        show_alert=True,
                    )
                    return False
                if face_asset and face_asset.status == "failed_error":
                    await answer_alert(
                        "⚠️ Не удалось подготовить фото. Загрузите фото ещё раз.",
                        show_alert=True,
                    )
                    return False
            session = session_svc.get_active_session(user.id)
            session_id = None
            trial_v2_take = False
            trial_v2_used_reroll = False
            trial_trend_id = trend_id if trend_id != TREND_CUSTOM_ID else TREND_CUSTOM_ID
            trial_v2_svc = TrialV2Service(db)
            if getattr(user, "is_moderator", False):
                free_session = session_svc.create_free_preview_session(user.id)
                session_id = free_session.id
                ProductAnalyticsService(db).track("collection_started", user.id, session_id=session_id)
            elif session and session.pack_id != "free_preview":
                if not session_svc.use_take(session):
                    await answer_alert("Лимит пакета исчерпан. Выберите новый пакет.", show_alert=True)
                    await _send_packages_upsell(bot, chat_id, "Лимит текущего пакета исчерпан.")
                    return False
                session_id = session.id
                is_paid_active_flow = True
            elif trial_v2_svc.is_trial_v2_user(user) and (not is_copy_flow):
                allowed, reason = trial_v2_svc.can_start_take(user.id, trial_trend_id)
                if not allowed:
                    await answer_alert(reason or "Trial-лимит исчерпан. Купите пакет.", show_alert=True)
                    await _send_packages_upsell(bot, chat_id, reason or "В Trial доступно только 3 уникальных образа.")
                    return False
                free_session = session if (session and session.pack_id == "free_preview") else None
                if not free_session:
                    free_session = session_svc.create_free_preview_session(
                        user.id,
                        takes_limit=6,
                    )
                    ProductAnalyticsService(db).track("collection_started", user.id, session_id=free_session.id)
                session_id = free_session.id
                trial_v2_take = True
            elif (user.free_takes_used or 0) < 1:
                from sqlalchemy import update as sa_update, func
                res = db.execute(
                    sa_update(User)
                    .where(User.id == user.id, (User.free_takes_used == None) | (User.free_takes_used < 1))
                    .values(free_takes_used=func.coalesce(User.free_takes_used, 0) + 1)
                )
                if res.rowcount == 0:
                    await answer_alert("Бесплатное фото исчерпано. Купите пакет.", show_alert=True)
                    await _send_packages_upsell(bot, chat_id, "Бесплатное фото исчерпано.")
                    return False
                db.flush()
                free_session = session_svc.create_free_preview_session(user.id)
                session_id = free_session.id
                ProductAnalyticsService(db).track("collection_started", user.id, session_id=session_id)
            else:
                await answer_alert("Бесплатное фото исчерпано. Купите пакет.", show_alert=True)
                await _send_packages_upsell(bot, chat_id, "Бесплатное фото исчерпано.")
                return False
            if face_asset:
                FaceAssetService(db).set_session_if_missing(face_asset, session_id)
            take = take_svc.create_take(
                user_id=user.id,
                trend_id=trend_id if trend_id != TREND_CUSTOM_ID else None,
                take_type=take_type,
                session_id=session_id,
                custom_prompt=custom_prompt,
                image_size=image_size,
                input_file_ids=input_file_ids,
                input_local_paths=input_local_paths,
                face_asset_id=face_asset.id if face_asset else None,
                copy_reference_path=copy_ref,
            )
            if face_asset and face_asset.status == "pending":
                take.status = "awaiting_face_id"
                awaiting_face_asset = True
                db.add(take)
                db.flush()
                face_id_pending_takes.set(int(db.query(TakeModel.id).filter(TakeModel.status == "awaiting_face_id").count()))
            if trial_v2_take:
                ok_trial, err_trial, used_reroll = trial_v2_svc.register_take_started(
                    user_id=user.id,
                    trend_id=trial_trend_id,
                    take_id=take.id,
                )
                if not ok_trial:
                    try:
                        db.delete(take)
                        db.flush()
                    except Exception:
                        logger.exception("trial_v2_take_delete_failed", extra={"take_id": take.id})
                    await answer_alert(err_trial or "Trial-лимит исчерпан. Купите пакет.", show_alert=True)
                    return False
                trial_v2_used_reroll = bool(used_reroll)
                try:
                    analytics = ProductAnalyticsService(db)
                    analytics.track(
                        "trial_reroll_used" if trial_v2_used_reroll else "trial_slot_used",
                        user.id,
                        session_id=session_id,
                        trend_id=trend_id if trend_id != TREND_CUSTOM_ID else None,
                        take_id=take.id,
                        properties={"trial_trend_id": trial_trend_id},
                    )
                except Exception:
                    logger.exception("trial_v2_take_track_failed", extra={"user_id": telegram_id, "take_id": take.id})
            created_take_id = take.id
            audience = (data.get("audience_type") or "").strip().lower() or AUDIENCE_WOMEN
            audit.log(
                actor_type="user",
                actor_id=telegram_id,
                action="take_started",
                entity_type="take",
                entity_id=created_take_id,
                payload={
                    "trend_id": trend_id,
                    "image_size": image_size,
                    "take_type": take_type,
                    "session_id": session_id,
                    "face_asset_id": getattr(take, "face_asset_id", None),
                    "awaiting_face_id": awaiting_face_asset,
                    "custom": bool(custom_prompt),
                    "audience": audience,
                    "trial_v2_take": trial_v2_take,
                    "trial_v2_used_reroll": trial_v2_used_reroll,
                },
            )
            _tid = trend_id if trend_id != TREND_CUSTOM_ID else None
            ProductAnalyticsService(db).track(
                "take_started",
                user.id,
                session_id=session_id,
                trend_id=_tid,
                take_id=created_take_id,
            )
            if _tid:
                ProductAnalyticsService(db).track(
                    "trend_take_started",
                    user.id,
                    session_id=session_id,
                    trend_id=_tid,
                    take_id=created_take_id,
                )
        ids_to_del = [message_ids_to_delete] if isinstance(message_ids_to_delete, int) else (message_ids_to_delete or [])
        valid_ids = [mid for mid in ids_to_del if mid is not None]
        await _try_delete_messages(bot, send_progress_to_chat_id, *valid_ids)
        if awaiting_face_asset:
            await bot.send_message(
                send_progress_to_chat_id,
                "⏳ Подготавливаем фото, стартуем автоматически…",
                reply_markup=main_menu_keyboard(),
            )
            await state.clear()
            logger.info("take_created_awaiting_face_id", extra={"user_id": telegram_id, "take_id": created_take_id})
            return True
        from app.core.celery_app import celery_app
        main_kb = main_menu_keyboard()
        intro_message_id = None
        if not is_paid_active_flow:
            intro_text = t("progress.generation_intro", GENERATION_INTRO_TEXT)
            intro_image_path = _generation_intro_image_path_for_audience(audience)
            if os.path.exists(intro_image_path):
                try:
                    photo_path, is_temp = path_for_telegram_photo(intro_image_path)
                    intro_msg = await bot.send_photo(
                        send_progress_to_chat_id,
                        photo=FSInputFile(photo_path),
                        caption=intro_text,
                        reply_markup=main_kb,
                    )
                    intro_message_id = intro_msg.message_id
                    if is_temp and os.path.isfile(photo_path):
                        try:
                            os.unlink(photo_path)
                        except OSError:
                            pass
                except Exception as e:
                    logger.warning("generation_intro_photo_failed", extra={"path": intro_image_path, "error": str(e)})
                    intro_msg = await bot.send_message(send_progress_to_chat_id, intro_text, reply_markup=main_kb)
                    intro_message_id = intro_msg.message_id
            else:
                intro_msg = await bot.send_message(send_progress_to_chat_id, intro_text, reply_markup=main_kb)
                intro_message_id = intro_msg.message_id
        progress_msg = await bot.send_message(
            send_progress_to_chat_id,
            t("progress.take_step_1", "⏳ Анализируем фото [🟩⬜⬜]\nСоздаём варианты · 1 из 3"),
        )
        try:
            celery_app.send_task(
                "app.workers.tasks.generate_take.generate_take",
                args=[created_take_id],
                kwargs={
                    "status_chat_id": str(send_progress_to_chat_id),
                    "status_message_id": progress_msg.message_id,
                    "intro_message_id": intro_message_id,
                },
            )
            enqueued = True
        except Exception as e:
            enqueue_error = f"{e.__class__.__name__}: {e}"
            logger.exception("take_enqueue_failed", extra={"user_id": telegram_id, "take_id": created_take_id})
            if created_take_id:
                try:
                    _mark_take_enqueue_failed(created_take_id, actor_id=telegram_id, reason=enqueue_error)
                except Exception:
                    logger.exception("take_enqueue_failed_compensation_error", extra={"take_id": created_take_id})
            await answer_alert("Не удалось запустить генерацию. Попробуйте ещё раз.", show_alert=True)
            await state.clear()
            return False
        await state.clear()
        logger.info("take_created", extra={"user_id": telegram_id, "take_id": created_take_id})
        return True
    except Exception as e:
        enqueue_error = f"{e.__class__.__name__}: {e}"
        logger.exception("Error in _create_job_and_start_generation", extra={"user_id": telegram_id})
        if created_take_id and not enqueued:
            try:
                _mark_take_enqueue_failed(created_take_id, actor_id=telegram_id, reason=enqueue_error)
            except Exception:
                logger.exception("take_enqueue_failed_compensation_error", extra={"take_id": created_take_id})
        await answer_alert(t("errors.try_again", "Ошибка. Попробуйте ещё раз."), show_alert=True)
        await state.clear()
        return False


@generation_router.callback_query(F.data.startswith("format:"))
async def select_format_and_generate(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Format selected (legacy: кнопки формата оставлены для совместимости) — create job and start generation."""
    format_key = callback.data.split(":", 1)[1]
    if format_key not in IMAGE_FORMATS:
        await callback.answer(t("errors.unknown_format", "Неизвестный формат"), show_alert=True)
        return
    telegram_id = str(callback.from_user.id) if callback.from_user else None
    if telegram_id:
        try:
            with get_db_session() as db:
                user = UserService(db).get_by_telegram_id(telegram_id)
                if user:
                    ProductAnalyticsService(db).track(
                        "format_selected",
                        user.id,
                        properties={"button_id": "format_selected", "format": format_key},
                    )
        except Exception:
            logger.exception("format_selected track failed")
    data = await state.get_data()

    async def answer_alert(text: str, show_alert: bool = False) -> None:
        await callback.answer(text, show_alert=show_alert)

    to_delete = [
        data.get("last_instruction_message_id"),
        data.get("last_bot_message_id"),
        callback.message.message_id,
    ]
    ok = await _create_job_and_start_generation(
        bot=bot,
        state=state,
        format_key=format_key,
        chat_id=callback.message.chat.id,
        message_ids_to_delete=[mid for mid in to_delete if mid is not None],
        from_user=callback.from_user,
        answer_alert=answer_alert,
        send_progress_to_chat_id=callback.message.chat.id,
    )
    if ok:
        await callback.answer("Генерация запущена!")


# --- Попробовать ещё раз: перегенерация с теми же параметрами ---
@generation_router.callback_query(F.data.startswith("regenerate:"))
async def regenerate_same(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Перегенерация с теми же трендом, промптом и настройками (тот же флоу)."""
    telegram_id = str(callback.from_user.id)
    job_id = callback.data.split(":", 1)[1].strip()
    if not job_id:
        await callback.answer(t("errors.general_short", "Ошибка."), show_alert=True)
        return

    try:
        # Загружаем job и проверяем доступ (без долгого удержания сессии)
        with get_db_session() as db:
            job_service = JobService(db)
            job = job_service.get(job_id)
            user = db.query(User).filter(User.telegram_id == telegram_id).first()
            if not user:
                await callback.answer(t("errors.start_first", "Сначала нажмите /start."), show_alert=True)
                return
            if not job or str(job.user_id) != str(user.id):
                await callback.answer(t("errors.job_not_found", "Кадр не найден."), show_alert=True)
                return
            try:
                ProductAnalyticsService(db).track(
                    "button_click",
                    user.id,
                    properties={"button_id": "regenerate", "job_id": job_id},
                )
            except Exception:
                logger.exception("button_click track failed regenerate")
            if job.status not in {"SUCCEEDED", "FAILED"}:
                await callback.answer(t("errors.wait_current_generation", "Подождите завершения текущей генерации."), show_alert=True)
                return
            file_ids = list(job.input_file_ids or [])
            if "ref" in file_ids:
                await callback.answer(
                    "Перегенерация для этого фото недоступна. Загрузите фото заново через меню.",
                    show_alert=True,
                )
                return
            if not file_ids:
                await callback.answer(t("errors.no_source_photos", "Нет исходных фото для повтора."), show_alert=True)
                return
            trend_id = job.trend_id
            image_size = job.image_size or "1024x1024"
            custom_prompt = job.custom_prompt
            is_copy_flow = bool(job.used_copy_quota)

        # Скачиваем файлы по file_id (вне сессии БД)
        inputs_dir = os.path.join(settings.storage_base_path, "inputs")
        os.makedirs(inputs_dir, exist_ok=True)
        input_local_paths = []
        for i, fid in enumerate(file_ids):
            try:
                file = await bot.get_file(fid)
                ext = (os.path.splitext(file.file_path or "")[1]) or ".jpg"
                local_path = os.path.join(inputs_dir, f"regen_{job_id}_{i}_{fid[:16]}{ext}")
                await bot.download_file(file.file_path, local_path)
                if os.path.getsize(local_path) / (1024 * 1024) > settings.max_file_size_mb:
                    for p in input_local_paths:
                        try:
                            os.remove(p)
                        except OSError:
                            pass
                    await callback.answer(
                        tr("errors.file_too_large_max_only", "Файл слишком большой. Максимум {max_mb} МБ.", max_mb=settings.max_file_size_mb),
                        show_alert=True,
                    )
                    return
                input_local_paths.append(local_path)
            except Exception as e:
                logger.warning("regenerate_download_failed", extra={"file_id": fid, "error": str(e)})
                for p in input_local_paths:
                    try:
                        os.remove(p)
                    except OSError:
                        pass
                await callback.answer(
                    "Не удалось загрузить фото. Попробуйте заново через меню.",
                    show_alert=True,
                )
                return

        # Квота, создание джоба, отправка в воркер
        with get_db_session() as db:
            user_service = UserService(db)
            trend_service = TrendService(db)
            job_service = JobService(db)
            audit = AuditService(db)
            user = user_service.get_by_telegram_id(telegram_id)
            if not user:
                await callback.answer(t("errors.start_again", "Ошибка. Нажмите /start."), show_alert=True)
                return
            if trend_id != TREND_CUSTOM_ID:
                trend = trend_service.get(trend_id)
                if not trend or not trend.enabled:
                    await callback.answer(t("errors.trend_no_longer", "Тренд больше недоступен."), show_alert=True)
                    return

            used_free_quota = False
            used_copy_quota = False
            if is_copy_flow:
                used_copy_quota = user_service.try_use_copy_generation(user)
                db.refresh(user)
            else:
                used_free_quota = user_service.try_use_free_generation(user)
                db.refresh(user)

            if not used_free_quota and not used_copy_quota:
                if not user_service.can_reserve(user, settings.generation_cost_tokens):
                    balance_rejected_total.inc()
                    sec = SecuritySettingsService(db).get_or_create()
                    if is_copy_flow:
                        limit = getattr(sec, "copy_generations_per_user", 1)
                        msg = f"Бесплатное фото «Сделать такую же» ({limit}/аккаунт) исчерпано. Купите пакет."
                    else:
                        limit = getattr(sec, "free_generations_per_user", 3)
                        msg = f"Бесплатные фото ({limit}/аккаунт) исчерпаны. Купите пакет."
                    await callback.answer(msg, show_alert=True)
                    return
                new_job_id = str(uuid4())
                if not user_service.hold_tokens(user, new_job_id, settings.generation_cost_tokens):
                    balance_rejected_total.inc()
                    await callback.answer(t("errors.reserve_tokens_failed", "Недостаточно доступа. Купите пакет."), show_alert=True)
                    return
            else:
                new_job_id = None

            reserved_for_job = 0 if (used_free_quota or used_copy_quota) else settings.generation_cost_tokens
            new_job = job_service.create_job(
                user_id=user.id,
                trend_id=trend_id,
                input_file_ids=file_ids,
                input_local_paths=input_local_paths,
                reserved_tokens=reserved_for_job,
                used_free_quota=used_free_quota,
                used_copy_quota=used_copy_quota,
                job_id=new_job_id,
                custom_prompt=custom_prompt,
                image_size=image_size,
            )
            created_job_id = new_job.job_id
            audit.log(
                actor_type="user",
                actor_id=telegram_id,
                action="job_created",
                entity_type="job",
                entity_id=created_job_id,
                payload={
                    "trend_id": trend_id,
                    "image_size": image_size,
                    "regenerate_of": job_id,
                },
            )
            ProductAnalyticsService(db).track(
                "regenerate_clicked",
                user.id,
                job_id=job_id,
                trend_id=trend_id if trend_id != TREND_CUSTOM_ID else None,
            )

        from app.core.celery_app import celery_app

        progress_msg = await callback.message.answer(
            "⏳ Перегенерация с теми же настройками...",
        )
        celery_app.send_task(
            "app.workers.tasks.generation_v2.generate_image",
            args=[created_job_id],
            kwargs={
                "status_chat_id": str(callback.message.chat.id),
                "status_message_id": progress_msg.message_id,
            },
        )
        jobs_created_total.labels(trend_id=trend_id or "unknown").inc()
        await state.clear()
        await callback.answer(t("errors.regenerate_launched", "Генерация запущена!"))
        logger.info("job_regenerate", extra={"user_id": telegram_id, "job_id": created_job_id, "regenerate_of": job_id})
    except Exception:
        logger.exception("Error in regenerate_same", extra={"user_id": telegram_id, "job_id": job_id})
        await callback.answer(t("errors.try_again", "Ошибка. Попробуйте ещё раз."), show_alert=True)
