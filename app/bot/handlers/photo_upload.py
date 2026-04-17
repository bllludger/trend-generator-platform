"""Handlers for photo upload flow: audience selection, consent, photo receipt."""
import asyncio
import logging
import os
from uuid import uuid4
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from datetime import datetime, timezone
from app.bot.states import BotStates
from app.bot.helpers import t, tr, get_db_session, _document_image_ext, _try_delete_messages, logger
from app.bot.keyboards import (
    main_menu_keyboard,
    themes_keyboard,
    trends_in_theme_keyboard,
    audience_keyboard,
    create_photo_only_keyboard,
)
from app.bot.constants import (
    RULE_IMAGE_PATH, SUCCESS_IMAGE_PATH, TREND_CUSTOM_ID, TRENDS_PER_PAGE,
    DEFAULT_ASPECT_RATIO, AUDIENCE_MEN_OFFRAMP_TEXT,
    PHOTO_ACCEPTED_CAPTION_DEFAULT, REQUEST_PHOTO_TEXT_DEFAULT, AUDIENCE_PROMPT_DEFAULT,
)
from app.core.config import settings
from app.constants import AUDIENCE_COUPLES, AUDIENCE_MEN, AUDIENCE_WOMEN, audience_in_target_audiences
from app.services.users.service import UserService
from app.services.themes.service import ThemeService
from app.services.trends.service import TrendService
from app.services.takes.service import TakeService
from app.services.sessions.service import SessionService
from app.services.audit.service import AuditService
from app.services.product_analytics.service import ProductAnalyticsService
from app.services.input_photo_analyzer import analyze_input_photo
from app.services.face_id.asset_service import FaceAssetService
from app.services.face_id.client import enqueue_face_id_processing
from app.services.face_id.settings_service import FaceIdSettingsService
from app.utils.metrics import photo_uploaded_total, face_id_fallback_total, face_id_requests_total
from app.utils.telegram_photo import path_for_telegram_photo
from app.bot.handlers.generation import _create_job_and_start_generation

photo_upload_router = Router()


def _is_new_user_for_limited_menu(user) -> bool:
    """Show only 'create photo' menu until first photo upload for brand-new users."""
    if not user:
        return False
    return (
        (getattr(user, "free_takes_used", 0) or 0) == 0
        and (getattr(user, "total_purchased", 0) or 0) == 0
        and (getattr(user, "token_balance", 0) or 0) == 0
        and (getattr(user, "copy_generations_used", 0) or 0) == 0
    )


async def _prepare_face_asset_for_trend_flow(
    *,
    user_id: str,
    session_id: str | None,
    chat_id: int,
    source_path: str,
) -> str | None:
    """
    Создать face_asset и отправить задачу в face-id сервис.
    При недоступности face-id сразу переводим в ready_fallback (оригинал).
    """
    request_id = str(uuid4())
    with get_db_session() as db:
        settings_svc = FaceIdSettingsService(db)
        asset_svc = FaceAssetService(db)
        face_cfg = settings_svc.as_dict()
        asset = asset_svc.create_pending(
            user_id=user_id,
            session_id=session_id,
            chat_id=str(chat_id),
            flow="trend",
            source_path=source_path,
            request_id=request_id,
        )
        if not bool(face_cfg.get("enabled", True)):
            asset_svc.apply_callback(
                asset=asset,
                event_id=f"local-disabled-{uuid4()}",
                status="ready_fallback",
                faces_detected=0,
                selected_path=source_path,
                source_path=source_path,
                detector_meta={"reason": "face_id_disabled"},
            )
            face_id_requests_total.labels(status="fallback").inc()
            face_id_fallback_total.labels(reason="disabled").inc()
            db.commit()
            return asset.id

        detector_config = {
            "min_detection_confidence": face_cfg.get("min_detection_confidence", 0.6),
            "model_selection": face_cfg.get("model_selection", 1),
            "crop_pad_left": face_cfg.get("crop_pad_left", 0.55),
            "crop_pad_right": face_cfg.get("crop_pad_right", 0.55),
            "crop_pad_top": face_cfg.get("crop_pad_top", 0.7),
            "crop_pad_bottom": face_cfg.get("crop_pad_bottom", 0.35),
            "max_faces_allowed": face_cfg.get("max_faces_allowed", 1),
            "no_face_policy": face_cfg.get("no_face_policy", "fallback_original"),
            "multi_face_policy": face_cfg.get("multi_face_policy", "fail_generation"),
            "callback_timeout_seconds": face_cfg.get("callback_timeout_seconds", 2.0),
            "callback_max_retries": face_cfg.get("callback_max_retries", 3),
            "callback_backoff_seconds": face_cfg.get("callback_backoff_seconds", 1.0),
        }
        enqueued = await enqueue_face_id_processing(
            asset_id=asset.id,
            source_path=source_path,
            flow="trend",
            user_id=user_id,
            chat_id=str(chat_id),
            request_id=request_id,
            detector_config=detector_config,
        )
        if enqueued:
            face_id_requests_total.labels(status="queued").inc()
            db.commit()
            return asset.id

        asset_svc.apply_callback(
            asset=asset,
            event_id=f"local-fallback-{uuid4()}",
            status="ready_fallback",
            faces_detected=0,
            selected_path=source_path,
            source_path=source_path,
            detector_meta={"reason": "enqueue_unavailable"},
        )
        face_id_requests_total.labels(status="fallback").inc()
        face_id_fallback_total.labels(reason="enqueue_unavailable").inc()
        db.commit()
        return asset.id


@photo_upload_router.message(lambda m: (m.text or "").strip() == t("menu.btn.create_photo", "🔥 Создать фото"))
async def request_photo(message: Message, state: FSMContext, bot: Bot):
    """User clicks 'Create photo' → сначала выбор ЦА, затем запрос фото."""
    telegram_id = str(message.from_user.id) if message.from_user else None
    try:
        if telegram_id:
            try:
                with get_db_session() as db:
                    user = UserService(db).get_or_create_user(
                        telegram_id,
                        telegram_username=message.from_user.username,
                        telegram_first_name=message.from_user.first_name,
                        telegram_last_name=message.from_user.last_name,
                    )
                    ProductAnalyticsService(db).track("button_click", user.id, properties={"button_id": "menu_create_photo"})
                    await state.update_data(limited_menu_until_first_photo=_is_new_user_for_limited_menu(user))
            except Exception:
                logger.exception("button_click track failed menu_create_photo")
        data = await state.get_data()
        after_sub_msg_id = data.get("after_subscription_message_id")
        if after_sub_msg_id:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=after_sub_msg_id)
            except Exception:
                pass
            await state.update_data(after_subscription_message_id=None)

        await state.set_state(BotStates.waiting_for_audience)
        sent = await message.answer(
            t("audience.prompt", AUDIENCE_PROMPT_DEFAULT),
            reply_markup=audience_keyboard(),
        )
        await state.update_data(
            last_bot_message_id=sent.message_id,
            selected_trend_id=None,
            selected_trend_name=None,
        )
    except Exception:
        logger.exception("Error in request_photo")
        await message.answer(t("errors.try_later", "Произошла ошибка. Попробуйте позже."), reply_markup=main_menu_keyboard())


@photo_upload_router.callback_query(F.data.startswith("audience:"))
async def on_audience_selected(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Выбор ЦА: сохраняем в state, логируем audit, переходим к запросу фото."""
    audience = callback.data.replace("audience:", "").strip().lower()
    if audience not in (AUDIENCE_WOMEN, AUDIENCE_MEN, AUDIENCE_COUPLES):
        await callback.answer()
        return
    try:
        await state.update_data(audience_type=audience)
        await state.set_state(BotStates.waiting_for_photo)
        await callback.answer()

        telegram_id = str(callback.from_user.id) if callback.from_user else None
        if telegram_id:
            try:
                with get_db_session() as db:
                    AuditService(db).log(
                        actor_type="user",
                        actor_id=telegram_id,
                        action="audience_selected",
                        entity_type="user",
                        entity_id=telegram_id,
                        payload={"audience": audience},
                    )
            except Exception as e:
                logger.warning("Audit audience_selected failed: %s", e)

        request_text = t("flow.request_photo", REQUEST_PHOTO_TEXT_DEFAULT)
        first_sent = None
        data = await state.get_data()
        limited_menu = bool(data.get("limited_menu_until_first_photo"))
        current_menu_keyboard = create_photo_only_keyboard() if limited_menu else main_menu_keyboard()
        if os.path.exists(RULE_IMAGE_PATH):
            try:
                await callback.message.delete()
                photo_path, is_temp = path_for_telegram_photo(RULE_IMAGE_PATH)
                first_sent = await callback.message.answer_photo(
                    photo=FSInputFile(photo_path),
                    caption=request_text,
                    parse_mode="HTML",
                    reply_markup=current_menu_keyboard,
                )
                if is_temp and os.path.isfile(photo_path):
                    try:
                        os.unlink(photo_path)
                    except OSError:
                        pass
            except Exception as e:
                logger.warning("rule_photo_failed", extra={"path": RULE_IMAGE_PATH, "error": str(e)})
                first_sent = await callback.message.answer(
                    request_text,
                    parse_mode="HTML",
                    reply_markup=current_menu_keyboard,
                )
        else:
            await callback.message.delete()
            first_sent = await callback.message.answer(
                request_text,
                parse_mode="HTML",
                reply_markup=current_menu_keyboard,
            )
        update_data = {"last_bot_message_id": first_sent.message_id}
        if first_sent is not None:
            update_data["photo_request_message_id"] = first_sent.message_id
        await state.update_data(**update_data)
    except Exception:
        logger.exception("Error in on_audience_selected")
        await callback.answer(t("errors.try_later", "Произошла ошибка. Попробуйте позже."), show_alert=True)
        try:
            await callback.message.answer(
                t("nav.upload_photo_or_btn", "Отправьте фото или нажмите «🔥 Создать фото»."),
                reply_markup=main_menu_keyboard(),
            )
        except Exception:
            pass


# --- Consent + Data Deletion ---

@photo_upload_router.callback_query(F.data == "accept_consent")
async def accept_consent(callback: CallbackQuery, state: FSMContext):
    """User accepts privacy consent."""
    telegram_id = str(callback.from_user.id)
    try:
        with get_db_session() as db:
            user_svc = UserService(db)
            user = user_svc.get_or_create_user(
                telegram_id,
                telegram_username=callback.from_user.username,
                telegram_first_name=callback.from_user.first_name,
                telegram_last_name=callback.from_user.last_name,
            )
            user.consent_accepted_at = datetime.now(timezone.utc)
            db.add(user)
            try:
                ProductAnalyticsService(db).track("consent_accepted", user.id, properties={"button_id": "accept_consent"})
            except Exception:
                logger.exception("consent_accepted track failed")

        await callback.answer("✅ Согласие принято")
        await callback.message.answer(
            "👍 Отлично! Теперь отправьте фото.",
            reply_markup=main_menu_keyboard(),
        )
    except Exception:
        logger.exception("accept_consent error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)


@photo_upload_router.message(Command("deletemydata"))
async def cmd_delete_my_data(message: Message, state: FSMContext):
    """User requests deletion of all their data."""
    telegram_id = str(message.from_user.id)
    try:
        with get_db_session() as db:
            user_svc = UserService(db)
            user = user_svc.get_or_create_user(
                telegram_id,
                telegram_username=message.from_user.username,
                telegram_first_name=message.from_user.first_name,
                telegram_last_name=message.from_user.last_name,
            )
            user.data_deletion_requested_at = datetime.now(timezone.utc)
            db.add(user)
            user_id = user.id
            try:
                ProductAnalyticsService(db).track("button_click", user_id, properties={"button_id": "deletemydata"})
            except Exception:
                logger.exception("button_click track failed deletemydata")
        from app.core.celery_app import celery_app as _celery
        _celery.send_task(
            "app.workers.tasks.delete_user_data.delete_user_data",
            args=[user_id],
        )
        await message.answer(
            "🗑 Запрос на удаление данных принят.\n"
            "Данные будут удалены в течение 72 часов.\n"
            "Мы уведомим вас о завершении."
        )
    except Exception:
        logger.exception("cmd_delete_my_data error", extra={"user_id": telegram_id})
        await message.answer("❌ Ошибка при запросе удаления данных.")


# --- Step 1: Receive photo, save and show trends ---
@photo_upload_router.message(BotStates.waiting_for_photo, F.photo)
async def handle_photo_step1(message: Message, state: FSMContext, bot: Bot):
    """Save photo and show trend selection (or 'Своя идея')."""
    telegram_id = str(message.from_user.id)
    
    try:
        # Consent check (можно отключить через REQUIRE_PHOTO_CONSENT=false)
        if settings.require_photo_consent:
            with get_db_session() as db:
                user_svc_consent = UserService(db)
                u_consent = user_svc_consent.get_or_create_user(
                    telegram_id,
                    telegram_username=message.from_user.username,
                    telegram_first_name=message.from_user.first_name,
                    telegram_last_name=message.from_user.last_name,
                )
                if not u_consent.consent_accepted_at:
                    await message.answer(
                        "📋 Перед загрузкой фото подтвердите согласие:\n\n"
                        "• Используйте только свои фото или фото с согласием владельца\n"
                        "• Входные данные хранятся 30 дней, результаты — 90 дней\n"
                        "• Вы можете удалить данные командой /deletemydata\n\n"
                        "Нажмите «Принимаю» чтобы продолжить.",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="✅ Принимаю", callback_data="accept_consent")],
                            [InlineKeyboardButton(text="ℹ️ Подробнее", url="https://nanobanana.ai/privacy")],
                        ]),
                    )
                    return

        data_early = await state.get_data()
        audience = (data_early.get("audience_type") or "").strip().lower() or AUDIENCE_WOMEN
        if audience == AUDIENCE_MEN:
            await message.answer(
                t("audience.men_offramp", AUDIENCE_MEN_OFFRAMP_TEXT),
                reply_markup=main_menu_keyboard(),
            )
            await state.clear()
            return

        # Validate photo
        photo = message.photo[-1]
        _, ext = os.path.splitext(photo.file_id)
        if ext and ext.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            await message.answer(t("flow.only_jpg_png_webp", "Поддерживаются только JPG, PNG, WEBP."))
            return

        face_user_id: str | None = None
        face_session_id: str | None = None
        with get_db_session() as db:
            user_service = UserService(db)
            theme_service = ThemeService(db)
            trend_service = TrendService(db)
            u = message.from_user
            user = user_service.get_or_create_user(
                telegram_id,
                telegram_username=u.username,
                telegram_first_name=u.first_name,
                telegram_last_name=u.last_name,
            )
            face_user_id = user.id
            active_session = SessionService(db).get_active_session(user.id)
            face_session_id = active_session.id if active_session else None
            theme_ids_with_trends = trend_service.list_theme_ids_with_active_trends(audience)
            all_themes = theme_service.list_all()
            themes = [t for t in all_themes if t.enabled and t.id in theme_ids_with_trends]
            themes_data = [{"id": t.id, "name": t.name, "emoji": t.emoji or ""} for t in themes]

            # Download and save photo
            file = await bot.get_file(photo.file_id)
            inputs_dir = os.path.join(settings.storage_base_path, "inputs")
            os.makedirs(inputs_dir, exist_ok=True)
            local_path = os.path.join(inputs_dir, f"{photo.file_id}.jpg")
            await bot.download_file(file.file_path, local_path)
            size_mb = os.path.getsize(local_path) / (1024 * 1024)
            if size_mb > settings.max_file_size_mb:
                try:
                    os.remove(local_path)
                except OSError:
                    pass
                await message.answer(
                    tr("errors.file_too_large_max", "Файл слишком большой ({size_mb:.1f} МБ). Максимум {max_mb} МБ.", size_mb=size_mb, max_mb=settings.max_file_size_mb)
                )
                return
        face_asset_id = None
        if face_user_id:
            face_asset_id = await _prepare_face_asset_for_trend_flow(
                user_id=face_user_id,
                session_id=face_session_id,
                chat_id=message.chat.id,
                source_path=local_path,
            )
        await state.update_data(
            photo_file_id=photo.file_id,
            photo_local_path=local_path,
            face_asset_id=face_asset_id,
        )
        data = await state.get_data()

        # Collection: first photo for the whole session — save to session and start step 0
        with get_db_session() as db:
            user_svc = UserService(db)
            session_svc = SessionService(db)
            analytics = ProductAnalyticsService(db)
            face_asset_svc = FaceAssetService(db)
            u = user_svc.get_or_create_user(
                telegram_id,
                telegram_username=message.from_user.username,
                telegram_first_name=message.from_user.first_name,
                telegram_last_name=message.from_user.last_name,
            )
            session = session_svc.get_active_session(u.id)
            face_asset_id = data.get("face_asset_id")
            face_asset = face_asset_svc.get(face_asset_id) if isinstance(face_asset_id, str) and face_asset_id else None
            if session and session_svc.is_collection(session) and not session.input_photo_path:
                session_svc.set_input_photo(session, local_path, photo.file_id)
                trend_id = session_svc.get_next_trend_id(session)
                if trend_id:
                    trend_svc = TrendService(db)
                    take_svc = TakeService(db)
                    trend = trend_svc.get(trend_id)
                    trend_name = trend.name if trend else trend_id
                    if face_asset and face_asset.status == "failed_multi_face":
                        await message.answer("❌ На фото несколько лиц. Загрузите селфи с одним человеком.")
                        await state.clear()
                        return
                    take = take_svc.create_take(
                        user_id=u.id,
                        trend_id=trend_id,
                        input_file_ids=[photo.file_id],
                        input_local_paths=[local_path],
                        image_size="1024x1024",
                        face_asset_id=face_asset.id if face_asset else None,
                    )
                    take.step_index = 0
                    take.is_reroll = False
                    if face_asset and face_asset.status == "pending":
                        take.status = "awaiting_face_id"
                    db.add(take)
                    session_svc.attach_take_to_session(take, session)
                    session_svc.advance_step(session)
                    take_id = take.id
                    analytics.track_funnel_step(
                        "photo_uploaded",
                        u.id,
                        session_id=session.id,
                        source_component="bot",
                    )
                    photo_uploaded_total.inc()
                    try:
                        analysis = analyze_input_photo(local_path)
                        analytics.track(
                            "input_photo_analyzed", u.id, session_id=session.id, properties=analysis
                        )
                    except Exception as e:
                        logger.warning("input_photo_analyzed failed: %s", e)

                    if face_asset and face_asset.status == "pending":
                        await message.answer("⏳ Подготавливаем фото, стартуем автоматически…")
                    else:
                        from app.core.celery_app import celery_app as _celery

                        status_msg = await message.answer(f"⏳ Образ 1 из {len(session.playlist)} — {trend_name}...")
                        _celery.send_task(
                            "app.workers.tasks.generate_take.generate_take",
                            args=[take_id],
                            kwargs={
                                "status_chat_id": str(message.chat.id),
                                "status_message_id": status_msg.message_id,
                            },
                        )
                    await state.set_state(BotStates.viewing_take_result)
                    return

            analytics.track_funnel_step(
                "photo_uploaded",
                u.id,
                session_id=session.id if session else None,
                source_component="bot",
            )
            photo_uploaded_total.inc()
            try:
                analysis = analyze_input_photo(local_path)
                analytics.track(
                    "input_photo_analyzed", u.id, session_id=session.id if session else None, properties=analysis
                )
            except Exception as e:
                logger.warning("input_photo_analyzed failed: %s", e)
        data = await state.get_data()
        audience = (data.get("audience_type") or "").strip().lower() or AUDIENCE_WOMEN
        # Deep link: trend already selected — skip trend choice, go to format (проверяем ЦА)
        pre_selected_id = data.get("selected_trend_id")
        if pre_selected_id and pre_selected_id != TREND_CUSTOM_ID:
            with get_db_session() as db:
                trend = TrendService(db).get(pre_selected_id)
                if trend and trend.enabled:
                    if not audience_in_target_audiences(audience, getattr(trend, "target_audiences", None)):
                        await message.answer(
                            t("audience.trend_unavailable_audience", "Тренд недоступен для выбранной целевой аудитории."),
                            reply_markup=main_menu_keyboard(),
                        )
                        await state.clear()
                        return
                    async def _answer_alert(text: str, show_alert: bool = False) -> None:
                        await message.answer(text, reply_markup=main_menu_keyboard())
                    ok = await _create_job_and_start_generation(
                        bot=bot,
                        state=state,
                        format_key=DEFAULT_ASPECT_RATIO,
                        chat_id=message.chat.id,
                        message_ids_to_delete=data.get("last_bot_message_id"),
                        from_user=message.from_user,
                        answer_alert=_answer_alert,
                        send_progress_to_chat_id=message.chat.id,
                    )
                    if ok:
                        pass
                    logger.info("photo_received_deeplink", extra={"user_id": telegram_id, "trend_id": pre_selected_id})
                    return
        # Диплинк на тематику: показать сразу тренды этой тематики (первая страница)
        preselected_theme_id = data.get("preselected_theme_id")
        if preselected_theme_id:
            with get_db_session() as db2:
                theme_svc = ThemeService(db2)
                trend_svc = TrendService(db2)
                theme = theme_svc.get(preselected_theme_id)
                if theme and theme.enabled:
                    trends = trend_svc.list_active_by_theme(preselected_theme_id, audience)
                    if trends:
                        total_pages = (len(trends) + TRENDS_PER_PAGE - 1) // TRENDS_PER_PAGE
                        trends_page = trends[:TRENDS_PER_PAGE]
                        trends_data = [{"id": t.id, "name": t.name, "emoji": t.emoji or ""} for t in trends_page]
                        theme_name_display = f"{theme.emoji or ''} {theme.name}".strip()
                        await state.set_state(BotStates.waiting_for_trend)
                        await state.update_data(
                            current_theme_id=preselected_theme_id,
                            current_theme_page=0,
                            preselected_theme_id=None,
                        )
                        await _try_delete_messages(bot, message.chat.id, data.get("last_bot_message_id"), message.message_id)
                        caption = tr(
                            "flow.theme_page_caption",
                            "Тематика: {theme_name} — стр. {current} из {total}",
                            theme_name=theme_name_display,
                            current=1,
                            total=total_pages,
                        )
                        sent = await message.answer(
                            caption,
                            reply_markup=trends_in_theme_keyboard(preselected_theme_id, trends_data, 0, total_pages),
                        )
                        await state.update_data(last_bot_message_id=sent.message_id)
                        logger.info("photo_received_deeplink_theme", extra={"user_id": telegram_id, "theme_id": preselected_theme_id})
                        return
        await state.set_state(BotStates.waiting_for_trend)
        await state.update_data(preselected_theme_id=None)
        await _try_delete_messages(
            bot, message.chat.id,
            data.get("photo_request_message_id"),
            data.get("last_bot_message_id"),
        )
        caption = t("flow.photo_accepted_choose_theme", PHOTO_ACCEPTED_CAPTION_DEFAULT)
        if os.path.exists(SUCCESS_IMAGE_PATH):
            try:
                photo_path, is_temp = path_for_telegram_photo(SUCCESS_IMAGE_PATH)
                sent = await message.answer_photo(
                    photo=FSInputFile(photo_path),
                    caption=caption,
                    reply_markup=themes_keyboard(themes_data),
                )
                if is_temp and os.path.isfile(photo_path):
                    try:
                        os.unlink(photo_path)
                    except OSError:
                        pass
            except Exception as e:
                logger.warning("success_photo_failed", extra={"path": SUCCESS_IMAGE_PATH, "error": str(e)})
                sent = await message.answer(caption, reply_markup=themes_keyboard(themes_data))
        else:
            sent = await message.answer(caption, reply_markup=themes_keyboard(themes_data))
        await state.update_data(last_bot_message_id=sent.message_id, photo_request_message_id=None)
        logger.info("photo_received", extra={"user_id": telegram_id})
    except Exception:
        logger.exception("Error in handle_photo_step1", extra={"user_id": telegram_id})
        await message.answer(t("errors.upload_photo", "Ошибка при загрузке фото. Попробуйте ещё раз."))
        await state.clear()


@photo_upload_router.message(BotStates.waiting_for_photo, F.document)
async def handle_photo_as_document_step1(message: Message, state: FSMContext, bot: Bot):
    """Accept image sent as document (no compression) — same flow as photo."""
    telegram_id = str(message.from_user.id)
    doc = message.document
    if not doc:
        await message.answer(t("errors.try_later_short", "Ошибка. Попробуйте позже."))
        return
    ext = _document_image_ext(doc.mime_type, doc.file_name)
    if not ext:
        await message.answer(t("flow.only_images", "Поддерживаются только изображения: JPG, PNG, WEBP. Отправьте файл с фото."))
        return
    try:
        data_early = await state.get_data()
        audience = (data_early.get("audience_type") or "").strip().lower() or AUDIENCE_WOMEN
        if audience == AUDIENCE_MEN:
            await message.answer(
                t("audience.men_offramp", AUDIENCE_MEN_OFFRAMP_TEXT),
                reply_markup=main_menu_keyboard(),
            )
            await state.clear()
            return
        face_user_id: str | None = None
        face_session_id: str | None = None
        with get_db_session() as db:
            user_service = UserService(db)
            theme_service = ThemeService(db)
            trend_service = TrendService(db)
            u = message.from_user
            user = user_service.get_or_create_user(
                telegram_id,
                telegram_username=u.username,
                telegram_first_name=u.first_name,
                telegram_last_name=u.last_name,
            )
            face_user_id = user.id
            active_session = SessionService(db).get_active_session(user.id)
            face_session_id = active_session.id if active_session else None
            theme_ids_with_trends = trend_service.list_theme_ids_with_active_trends(audience)
            all_themes = theme_service.list_all()
            themes = [t for t in all_themes if t.enabled and t.id in theme_ids_with_trends]
            themes_data = [{"id": t.id, "name": t.name, "emoji": t.emoji or ""} for t in themes]
            file = await bot.get_file(doc.file_id)
            inputs_dir = os.path.join(settings.storage_base_path, "inputs")
            os.makedirs(inputs_dir, exist_ok=True)
            local_path = os.path.join(inputs_dir, f"{doc.file_id}{ext}")
            await bot.download_file(file.file_path, local_path)
            size_mb = os.path.getsize(local_path) / (1024 * 1024)
            if size_mb > settings.max_file_size_mb:
                try:
                    os.remove(local_path)
                except OSError:
                    pass
                await message.answer(
                    tr("errors.file_too_large_max", "Файл слишком большой ({size_mb:.1f} МБ). Максимум {max_mb} МБ.", size_mb=size_mb, max_mb=settings.max_file_size_mb)
                )
                return
        face_asset_id = None
        if face_user_id:
            face_asset_id = await _prepare_face_asset_for_trend_flow(
                user_id=face_user_id,
                session_id=face_session_id,
                chat_id=message.chat.id,
                source_path=local_path,
            )
        await state.update_data(
            photo_file_id=doc.file_id,
            photo_local_path=local_path,
            face_asset_id=face_asset_id,
        )
        data = await state.get_data()
        pre_selected_id = data.get("selected_trend_id")
        if pre_selected_id and pre_selected_id != TREND_CUSTOM_ID:
            with get_db_session() as db:
                trend = TrendService(db).get(pre_selected_id)
                if trend and trend.enabled:
                    async def _answer_alert_doc(text: str, show_alert: bool = False) -> None:
                        await message.answer(text, reply_markup=main_menu_keyboard())
                    ok = await _create_job_and_start_generation(
                        bot=bot,
                        state=state,
                        format_key=DEFAULT_ASPECT_RATIO,
                        chat_id=message.chat.id,
                        message_ids_to_delete=data.get("last_bot_message_id"),
                        from_user=message.from_user,
                        answer_alert=_answer_alert_doc,
                        send_progress_to_chat_id=message.chat.id,
                    )
                    logger.info("photo_received_as_document_deeplink", extra={"user_id": telegram_id, "trend_id": pre_selected_id})
                    return
        preselected_theme_id = data.get("preselected_theme_id")
        if preselected_theme_id:
            with get_db_session() as db2:
                theme_svc = ThemeService(db2)
                trend_svc = TrendService(db2)
                theme = theme_svc.get(preselected_theme_id)
                if theme and theme.enabled:
                    trends = trend_svc.list_active_by_theme(preselected_theme_id, audience)
                    if trends:
                        total_pages = (len(trends) + TRENDS_PER_PAGE - 1) // TRENDS_PER_PAGE
                        trends_page = trends[:TRENDS_PER_PAGE]
                        trends_data = [{"id": t.id, "name": t.name, "emoji": t.emoji or ""} for t in trends_page]
                        theme_name_display = f"{theme.emoji or ''} {theme.name}".strip()
                        await state.set_state(BotStates.waiting_for_trend)
                        await state.update_data(
                            current_theme_id=preselected_theme_id,
                            current_theme_page=0,
                            preselected_theme_id=None,
                        )
                        await _try_delete_messages(bot, message.chat.id, data.get("last_bot_message_id"), message.message_id)
                        caption = tr(
                            "flow.theme_page_caption",
                            "Тематика: {theme_name} — стр. {current} из {total}",
                            theme_name=theme_name_display,
                            current=1,
                            total=total_pages,
                        )
                        sent = await message.answer(
                            caption,
                            reply_markup=trends_in_theme_keyboard(preselected_theme_id, trends_data, 0, total_pages),
                        )
                        await state.update_data(last_bot_message_id=sent.message_id)
                        logger.info("photo_received_as_document_deeplink_theme", extra={"user_id": telegram_id, "theme_id": preselected_theme_id})
                        return
        await state.set_state(BotStates.waiting_for_trend)
        await state.update_data(preselected_theme_id=None)
        await _try_delete_messages(
            bot, message.chat.id,
            data.get("photo_request_message_id"),
            data.get("last_bot_message_id"),
        )
        caption = t("flow.photo_accepted_choose_theme", PHOTO_ACCEPTED_CAPTION_DEFAULT)
        if os.path.exists(SUCCESS_IMAGE_PATH):
            try:
                photo_path, is_temp = path_for_telegram_photo(SUCCESS_IMAGE_PATH)
                sent = await message.answer_photo(
                    photo=FSInputFile(photo_path),
                    caption=caption,
                    reply_markup=themes_keyboard(themes_data),
                )
                if is_temp and os.path.isfile(photo_path):
                    try:
                        os.unlink(photo_path)
                    except OSError:
                        pass
            except Exception as e:
                logger.warning("success_photo_failed", extra={"path": SUCCESS_IMAGE_PATH, "error": str(e)})
                sent = await message.answer(caption, reply_markup=themes_keyboard(themes_data))
        else:
            sent = await message.answer(caption, reply_markup=themes_keyboard(themes_data))
        await state.update_data(last_bot_message_id=sent.message_id, photo_request_message_id=None)
        logger.info("photo_received_as_document", extra={"user_id": telegram_id})
    except Exception:
        logger.exception("Error in handle_photo_as_document_step1", extra={"user_id": telegram_id})
        await message.answer(t("errors.upload_file", "Ошибка при загрузке файла. Попробуйте ещё раз."))
        await state.clear()
