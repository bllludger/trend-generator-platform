import logging
import os

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy.orm import Session

from app.bot.states import BotStates
from app.bot.helpers import t, tr, get_db_session, _document_image_ext, redis_client, logger
from app.bot.keyboards import main_menu_keyboard
from app.bot.constants import TREND_CUSTOM_ID, DEFAULT_ASPECT_RATIO
from app.core.config import settings
from app.services.users.service import UserService
from app.services.trends.service import TrendService
from app.services.takes.service import TakeService
from app.services.sessions.service import SessionService
from app.services.audit.service import AuditService
from app.services.product_analytics.service import ProductAnalyticsService
from app.services.trial_v2.service import TrialV2Service
from app.services.idempotency import IdempotencyStore
from app.models.user import User
from app.models.take import Take as TakeModel

rescue_router = Router()

# --- Preview rescue flow: "Все 3 не подходят" → C1/E, reroll, other photo/trend ---
RESCUE_LIMIT_TTL_SECONDS = 30 * 24 * 60 * 60


def _rescue_reroll_limit_key(take_id: str) -> str:
    return f"rescue:reroll:{take_id}"


def _rescue_replace_limit_key(take_id: str) -> str:
    return f"rescue:replace:{take_id}"


def _load_rescue_take_with_access(db: Session, telegram_id: str, take_id: str) -> tuple[User | None, TakeModel | None]:
    user = UserService(db).get_by_telegram_id(telegram_id)
    take = TakeService(db).get_take(take_id)
    if not user or not take:
        return None, None
    if str(take.user_id) != str(user.id):
        return None, None
    return user, take


def _rescue_screen_c1(take_id: str) -> tuple[str, InlineKeyboardMarkup]:
    text = "Давайте перегенерируем. Выберите вариант:"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 С тем же фото", callback_data=f"rescue:reason:more:{take_id}")],
        [InlineKeyboardButton(text="📷 Загрузить другое фото", callback_data=f"rescue:other_photo:{take_id}")],
    ])
    return text, kb


def _rescue_screen_e(take_id: str) -> tuple[str, InlineKeyboardMarkup]:
    return _rescue_screen_c1(take_id)


def _rescue_screen_f(take_id: str) -> tuple[str, InlineKeyboardMarkup]:
    text = (
        "Иногда результат зависит от исходного фото. "
        "Лучше всего работают фото, где лицо видно четко, без сильных теней и перекрытий."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📷 Загрузить другое фото", callback_data=f"rescue:other_photo:{take_id}")],
        [InlineKeyboardButton(text="💡 Какое фото подойдет", callback_data=f"rescue:photo_tip:{take_id}")],
    ])
    return text, kb


def _rescue_screen_g(take_id: str) -> tuple[str, InlineKeyboardMarkup]:
    text = (
        "Лучше всего работают фото, где:\n"
        "• лицо видно прямо или почти прямо\n"
        "• нет сильных теней\n"
        "• глаза и контуры лица не закрыты\n"
        "• фото четкое"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📷 Загрузить другое фото", callback_data=f"rescue:other_photo:{take_id}")],
    ])
    return text, kb


def _rescue_screen_i(take_id: str) -> tuple[str, InlineKeyboardMarkup]:
    text = "Можно попробовать другой тренд."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎭 Попробовать другой тренд", callback_data="nav:menu")],
        [InlineKeyboardButton(text="💎 Открыть лучший вариант", callback_data="open_favorites")],
    ])
    return text, kb


async def _delete_rescue_prompt_message(callback: CallbackQuery) -> None:
    """Удалить промежуточный rescue-пост, чтобы не захламлять чат."""
    try:
        await callback.message.delete()
    except Exception:
        pass


@rescue_router.callback_query(F.data.startswith("rescue:reject_set:"))
async def rescue_reject_set(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """«Все 3 не подходят»: короткий флоу в 2 шага — reroll тем же фото или загрузка нового фото."""
    telegram_id = str(callback.from_user.id)
    take_id = (callback.data or "").split(":", 2)[-1].strip()
    if not take_id:
        await callback.answer("Ошибка", show_alert=True)
        return
    try:
        with get_db_session() as db:
            take_svc = TakeService(db)
            session_svc = SessionService(db)
            user_svc = UserService(db)
            take = take_svc.get_take(take_id)
            if not take:
                await callback.answer("Снимок не найден", show_alert=True)
                return
            user = user_svc.get_by_telegram_id(telegram_id)
            if not user or str(take.user_id) != str(user.id):
                await callback.answer("Нет доступа", show_alert=True)
                return
            is_reroll = getattr(take, "is_reroll", False)
            is_rescue_photo = getattr(take, "is_rescue_photo_replace", False)
            round_num = 2 if (is_reroll or is_rescue_photo) else 1
            try:
                ProductAnalyticsService(db).track(
                    "rescue_reject_set",
                    user.id,
                    take_id=take_id,
                    session_id=take.session_id,
                    trend_id=take.trend_id,
                    properties={"round": round_num},
                )
            except Exception:
                pass
        try:
            bundle_menu_key = f"trial:bundle_menu:{telegram_id}:{take_id}"
            stale_menu_id_raw = redis_client.get(bundle_menu_key)
            if stale_menu_id_raw:
                stale_menu_id = int(stale_menu_id_raw)
                try:
                    await bot.delete_message(chat_id=callback.message.chat.id, message_id=stale_menu_id)
                except Exception:
                    pass
                try:
                    redis_client.delete(bundle_menu_key)
                except Exception:
                    pass
        except Exception:
            logger.warning("rescue_remove_bundle_menu_failed", extra={"user_id": telegram_id, "take_id": take_id})

        text, kb = _rescue_screen_c1(take_id)
        try:
            # Вместо нового сообщения переиспользуем текущий пост с выбором 3 вариантов.
            await callback.message.edit_text(text, reply_markup=kb)
        except Exception:
            await callback.message.answer(text, reply_markup=kb)
        await callback.answer()
    except Exception:
        logger.exception("rescue_reject_set error", extra={"user_id": telegram_id})
        await callback.answer("Ошибка", show_alert=True)


@rescue_router.callback_query(F.data.startswith("rescue:reason:face:"))
async def rescue_reason_face(callback: CallbackQuery):
    """Legacy-кнопка: возвращаем в короткий rescue-флоу."""
    telegram_id = str(callback.from_user.id)
    take_id = (callback.data or "").split(":", 3)[-1].strip()
    if not take_id:
        await callback.answer()
        return
    try:
        with get_db_session() as db:
            user, take = _load_rescue_take_with_access(db, telegram_id, take_id)
            if not user or not take:
                await callback.answer("Нет доступа", show_alert=True)
                return
            try:
                ProductAnalyticsService(db).track(
                    "rescue_reason_face", user.id,
                    take_id=take_id, session_id=take.session_id, trend_id=take.trend_id,
                )
            except Exception:
                logger.exception("rescue_reason_face track failed", extra={"user_id": telegram_id, "take_id": take_id})
    except Exception:
        logger.exception("rescue_reason_face access error", extra={"user_id": telegram_id, "take_id": take_id})
        await callback.answer("Ошибка", show_alert=True)
        return
    text, kb = _rescue_screen_c1(take_id)
    await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


@rescue_router.callback_query(F.data.startswith("rescue:reason:style:"))
async def rescue_reason_style(callback: CallbackQuery):
    """Legacy-кнопка: возвращаем в короткий rescue-флоу."""
    telegram_id = str(callback.from_user.id)
    take_id = (callback.data or "").split(":", 3)[-1].strip()
    if not take_id:
        await callback.answer()
        return
    try:
        with get_db_session() as db:
            user, take = _load_rescue_take_with_access(db, telegram_id, take_id)
            if not user or not take:
                await callback.answer("Нет доступа", show_alert=True)
                return
            try:
                ProductAnalyticsService(db).track(
                    "rescue_reason_style", user.id,
                    take_id=take_id, session_id=take.session_id, trend_id=take.trend_id,
                )
            except Exception:
                logger.exception("rescue_reason_style track failed", extra={"user_id": telegram_id, "take_id": take_id})
    except Exception:
        logger.exception("rescue_reason_style access error", extra={"user_id": telegram_id, "take_id": take_id})
        await callback.answer("Ошибка", show_alert=True)
        return
    text, kb = _rescue_screen_c1(take_id)
    await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


@rescue_router.callback_query(F.data.startswith("rescue:reason:more:"))
async def rescue_reason_more(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Хочу еще варианты → один бесплатный reroll (новый Take, is_reroll=True). Для free_preview — paywall."""
    from app.bot.handlers.generation import _mark_take_enqueue_failed

    telegram_id = str(callback.from_user.id)
    take_id = (callback.data or "").split(":", 3)[-1].strip()
    if not take_id:
        await callback.answer("Ошибка", show_alert=True)
        return
    limit_key = _rescue_reroll_limit_key(take_id)
    limit_store = None
    limit_reserved = False
    launched = False
    keep_limit = False
    try:
        try:
            limit_store = IdempotencyStore()
            limit_reserved = limit_store.check_and_set(limit_key, ttl_seconds=RESCUE_LIMIT_TTL_SECONDS)
            if not limit_reserved:
                await callback.answer("Лимит повтора для этого набора уже использован.", show_alert=True)
                return
        except Exception as e:
            logger.warning("rescue_reroll_limit_unavailable", extra={"user_id": telegram_id, "take_id": take_id, "error": str(e)})

        with get_db_session() as db:
            take_svc = TakeService(db)
            session_svc = SessionService(db)
            user_svc = UserService(db)
            take = take_svc.get_take(take_id)
            if not take or not take.trend_id or not take.session_id:
                await callback.answer("Нельзя перегенерировать это фото", show_alert=True)
                return
            user = user_svc.get_by_telegram_id(telegram_id)
            if not user or str(take.user_id) != str(user.id):
                await callback.answer("Нет доступа", show_alert=True)
                return
            session = session_svc.get_session(take.session_id)
            if not session:
                await callback.answer("Сессия не найдена", show_alert=True)
                return
            is_paid_session = str(session.pack_id or "").strip().lower() != "free_preview"
            if is_paid_session:
                if not session_svc.use_take(session):
                    await callback.answer("Лимит пакета исчерпан. Выберите новый пакет.", show_alert=True)
                    return
            trial_v2_svc = TrialV2Service(db)
            use_trial_v2 = bool(getattr(user, "trial_v2_eligible", False)) and str(session.pack_id or "").strip().lower() == "free_preview"
            if use_trial_v2:
                allowed, reason = trial_v2_svc.can_start_take(user.id, take.trend_id or TREND_CUSTOM_ID)
                if not allowed:
                    await callback.answer(reason or "Trial-лимит для этого образа исчерпан.", show_alert=True)
                    return
            input_paths = list(take.input_local_paths or [])
            if not input_paths:
                await callback.answer("Нет исходного фото для повтора", show_alert=True)
                return
            first_path = input_paths[0] if isinstance(input_paths[0], str) else None
            if not first_path or not os.path.isfile(first_path):
                await callback.answer("Исходное фото недоступно. Начните заново с «Создать фото».", show_alert=True)
                return
            try:
                ProductAnalyticsService(db).track(
                    "rescue_reroll_started", user.id,
                    take_id=take_id, session_id=take.session_id, trend_id=take.trend_id,
                )
            except Exception:
                pass
            new_take = take_svc.create_take(
                user_id=user.id,
                trend_id=take.trend_id,
                session_id=take.session_id,
                image_size=take.image_size,
                input_file_ids=list(take.input_file_ids or []),
                input_local_paths=input_paths,
                is_reroll=True,
            )
            if use_trial_v2:
                ok_trial, err_trial, _ = trial_v2_svc.register_take_started(
                    user_id=user.id,
                    trend_id=take.trend_id or TREND_CUSTOM_ID,
                    take_id=new_take.id,
                )
                if not ok_trial:
                    try:
                        db.delete(new_take)
                        db.flush()
                    except Exception:
                        logger.exception("trial_v2_rescue_take_delete_failed", extra={"take_id": new_take.id})
                    await callback.answer(err_trial or "Trial-лимит для этого образа исчерпан.", show_alert=True)
                    return
                try:
                    ProductAnalyticsService(db).track(
                        "trial_reroll_used",
                        user.id,
                        take_id=new_take.id,
                        session_id=take.session_id,
                        trend_id=take.trend_id,
                    )
                except Exception:
                    logger.exception("trial_reroll_used_track_failed", extra={"user_id": telegram_id, "take_id": new_take.id})
            new_take_id = new_take.id
        chat_id = str(callback.message.chat.id)
        status_msg = await callback.message.answer("⏳ Генерируем новый набор из 3 вариантов…")
        from app.core.celery_app import celery_app
        try:
            celery_app.send_task(
                "app.workers.tasks.generate_take.generate_take",
                args=[new_take_id],
                kwargs={
                    "status_chat_id": chat_id,
                    "status_message_id": status_msg.message_id,
                },
            )
        except Exception:
            logger.exception("rescue_reroll_enqueue_failed", extra={"user_id": telegram_id, "take_id": new_take_id})
            _mark_take_enqueue_failed(new_take_id, actor_id=telegram_id)
            if limit_store is not None and limit_reserved:
                try:
                    limit_store.release(limit_key)
                    limit_reserved = False
                except Exception:
                    logger.warning("rescue_reroll_limit_release_failed", extra={"user_id": telegram_id, "take_id": take_id})
            await callback.answer("Не удалось запустить перегенерацию. Попробуйте ещё раз.", show_alert=True)
            return
        launched = True
        keep_limit = True
        await _delete_rescue_prompt_message(callback)
        await callback.answer()
    except Exception:
        logger.exception("rescue_reason_more error", extra={"user_id": telegram_id})
        if (not launched) and limit_store is not None and limit_reserved:
            try:
                limit_store.release(limit_key)
                limit_reserved = False
            except Exception:
                logger.warning("rescue_reroll_limit_release_failed", extra={"user_id": telegram_id, "take_id": take_id})
        await callback.answer("Ошибка. Попробуйте позже.", show_alert=True)
    finally:
        if limit_store is not None and limit_reserved and not keep_limit:
            try:
                limit_store.release(limit_key)
            except Exception:
                logger.warning("rescue_reroll_limit_release_failed", extra={"user_id": telegram_id, "take_id": take_id})


@rescue_router.callback_query(F.data.startswith("rescue:photo_tip:"))
async def rescue_photo_tip(callback: CallbackQuery):
    """Какое фото подойдет → экран G."""
    telegram_id = str(callback.from_user.id)
    take_id = (callback.data or "").split(":", 3)[-1].strip()
    if not take_id:
        await callback.answer()
        return
    try:
        with get_db_session() as db:
            user, take = _load_rescue_take_with_access(db, telegram_id, take_id)
            if not user or not take:
                await callback.answer("Нет доступа", show_alert=True)
                return
    except Exception:
        await callback.answer("Ошибка", show_alert=True)
        return
    text, kb = _rescue_screen_g(take_id)
    await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


@rescue_router.callback_query(F.data.startswith("rescue:other_photo:"))
async def rescue_other_photo(callback: CallbackQuery, state: FSMContext):
    """Загрузить другое фото: проверка лимита, переход в rescue_waiting_photo. Для free_preview — paywall."""
    telegram_id = str(callback.from_user.id)
    take_id = (callback.data or "").split(":", 3)[-1].strip()
    if not take_id:
        await callback.answer()
        return
    try:
        try:
            if IdempotencyStore().is_set(_rescue_replace_limit_key(take_id)):
                await callback.answer("Лимит замены фото для этого набора уже использован.", show_alert=True)
                return
        except Exception as e:
            logger.warning("rescue_replace_limit_unavailable", extra={"user_id": telegram_id, "take_id": take_id, "error": str(e)})

        with get_db_session() as db:
            take_svc = TakeService(db)
            session_svc = SessionService(db)
            user_svc = UserService(db)
            trial_v2_svc = TrialV2Service(db)
            take = take_svc.get_take(take_id)
            if not take or not take.session_id or not take.trend_id:
                await callback.answer("Снимок не найден", show_alert=True)
                return
            user = user_svc.get_by_telegram_id(telegram_id)
            if not user or str(take.user_id) != str(user.id):
                await callback.answer("Нет доступа", show_alert=True)
                return
            session = session_svc.get_session(take.session_id)
            if not session:
                await callback.answer("Сессия не найдена", show_alert=True)
                return
            use_trial_v2 = bool(getattr(user, "trial_v2_eligible", False)) and str(session.pack_id or "").strip().lower() == "free_preview"
            if use_trial_v2:
                allowed, reason = trial_v2_svc.can_start_take(user.id, take.trend_id or TREND_CUSTOM_ID)
                if not allowed:
                    await callback.answer(reason or "Trial-лимит для этого образа исчерпан.", show_alert=True)
                    return
            await state.set_state(BotStates.rescue_waiting_photo)
            await state.update_data(
                rescue_take_id=take_id,
                rescue_trend_id=take.trend_id,
                rescue_session_id=take.session_id,
                rescue_user_id=user.id,
                rescue_image_size=take.image_size,
            )
        await _delete_rescue_prompt_message(callback)
        await callback.message.answer("📷 Отправьте новое фото для этого тренда.")
        await callback.answer()
    except Exception:
        logger.exception("rescue_other_photo error", extra={"user_id": telegram_id})
        await callback.answer("Ошибка", show_alert=True)


@rescue_router.callback_query(F.data.startswith("rescue:other_trend:"))
async def rescue_other_trend(callback: CallbackQuery, state: FSMContext):
    """Попробовать другой тренд → экран I. Для free_preview — paywall."""
    telegram_id = str(callback.from_user.id)
    take_id = (callback.data or "").split(":", 3)[-1].strip()
    if not take_id:
        await callback.answer()
        return
    try:
        with get_db_session() as db:
            take = TakeService(db).get_take(take_id)
            user = UserService(db).get_by_telegram_id(telegram_id)
            if take and user and str(take.user_id) != str(user.id):
                await callback.answer("Нет доступа", show_alert=True)
                return
    except Exception:
        pass
    text, kb = _rescue_screen_i(take_id)
    await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


async def _rescue_save_photo_and_start_take(
    message: Message, bot: Bot, state: FSMContext, local_path: str, file_id: str
) -> bool:
    """Сохранить путь в state уже сделано снаружи. Создать Take (rescue photo replace) и поставить generate_take. Возвращает True при успехе."""
    from app.bot.handlers.generation import _mark_take_enqueue_failed

    data = await state.get_data()
    trend_id = data.get("rescue_trend_id")
    session_id = data.get("rescue_session_id")
    user_id = data.get("rescue_user_id")
    source_take_id = data.get("rescue_take_id")
    image_size = data.get("rescue_image_size") or "1024x1024"
    if not trend_id or not session_id or not user_id or not source_take_id:
        await message.answer("Сессия устарела. Начните заново с «Создать фото».", reply_markup=main_menu_keyboard())
        await state.clear()
        return False
    limit_key = _rescue_replace_limit_key(str(source_take_id))
    limit_store = None
    limit_reserved = False
    keep_limit = False
    new_take_id: str | None = None
    try:
        try:
            limit_store = IdempotencyStore()
            limit_reserved = limit_store.check_and_set(limit_key, ttl_seconds=RESCUE_LIMIT_TTL_SECONDS)
            if not limit_reserved:
                await message.answer("Лимит замены фото для этого набора уже использован.", reply_markup=main_menu_keyboard())
                await state.clear()
                return False
        except Exception as e:
            logger.warning("rescue_replace_limit_unavailable", extra={"take_id": source_take_id, "error": str(e)})

        with get_db_session() as db:
            take_svc = TakeService(db)
            session_svc = SessionService(db)
            trial_v2_svc = TrialV2Service(db)
            session = session_svc.get_session(session_id)
            if not session:
                await message.answer("Сессия не найдена. Начните заново.", reply_markup=main_menu_keyboard())
                await state.clear()
                return False
            is_paid_session = str(session.pack_id or "").strip().lower() != "free_preview"
            if is_paid_session:
                if not session_svc.use_take(session):
                    await message.answer("Лимит пакета исчерпан. Выберите новый пакет.", reply_markup=main_menu_keyboard())
                    await state.clear()
                    return False
            user = db.query(User).filter(User.id == str(user_id)).one_or_none()
            if not user:
                await message.answer("Пользователь не найден. Начните заново.", reply_markup=main_menu_keyboard())
                await state.clear()
                return False
            use_trial_v2 = bool(getattr(user, "trial_v2_eligible", False)) and str(session.pack_id or "").strip().lower() == "free_preview"
            if use_trial_v2:
                allowed, reason = trial_v2_svc.can_start_take(user.id, trend_id or TREND_CUSTOM_ID)
                if not allowed:
                    await message.answer(reason or "Trial-лимит для этого образа исчерпан.", reply_markup=main_menu_keyboard())
                    await state.clear()
                    return False
            new_take = take_svc.create_take(
                user_id=str(user_id),
                trend_id=trend_id,
                session_id=session_id,
                image_size=image_size,
                input_file_ids=[file_id],
                input_local_paths=[local_path],
                is_rescue_photo_replace=True,
            )
            new_take_id = new_take.id
            if use_trial_v2:
                ok_trial, err_trial, _ = trial_v2_svc.register_take_started(
                    user_id=user.id,
                    trend_id=trend_id or TREND_CUSTOM_ID,
                    take_id=new_take.id,
                )
                if not ok_trial:
                    try:
                        db.delete(new_take)
                        db.flush()
                    except Exception:
                        logger.exception("trial_v2_rescue_replace_take_delete_failed", extra={"take_id": new_take.id})
                    await message.answer(err_trial or "Trial-лимит для этого образа исчерпан.", reply_markup=main_menu_keyboard())
                    await state.clear()
                    return False
        await state.clear()
        status_msg = await message.answer("⏳ Генерируем новый набор из 3 вариантов по вашему фото…")
        from app.core.celery_app import celery_app
        try:
            celery_app.send_task(
                "app.workers.tasks.generate_take.generate_take",
                args=[new_take_id],
                kwargs={
                    "status_chat_id": str(message.chat.id),
                    "status_message_id": status_msg.message_id,
                },
            )
        except Exception:
            logger.exception("rescue_replace_enqueue_failed", extra={"take_id": new_take_id})
            if new_take_id:
                _mark_take_enqueue_failed(new_take_id)
            if limit_store is not None and limit_reserved:
                try:
                    limit_store.release(limit_key)
                    limit_reserved = False
                except Exception:
                    logger.warning("rescue_replace_limit_release_failed", extra={"take_id": source_take_id})
            await message.answer("Не удалось запустить генерацию. Попробуйте ещё раз.", reply_markup=main_menu_keyboard())
            return False
        keep_limit = True
        return True
    except Exception:
        logger.exception("rescue_save_photo_and_start_take error")
        if limit_store is not None and limit_reserved:
            try:
                limit_store.release(limit_key)
                limit_reserved = False
            except Exception:
                logger.warning("rescue_replace_limit_release_failed", extra={"take_id": source_take_id})
        if new_take_id:
            try:
                _mark_take_enqueue_failed(new_take_id)
            except Exception:
                logger.exception("rescue_replace_enqueue_compensation_error", extra={"take_id": new_take_id})
        await message.answer("Ошибка при создании снимка. Попробуйте ещё раз.", reply_markup=main_menu_keyboard())
        await state.clear()
        return False
    finally:
        if limit_store is not None and limit_reserved and not keep_limit:
            try:
                limit_store.release(limit_key)
            except Exception:
                logger.warning("rescue_replace_limit_release_failed", extra={"take_id": source_take_id})


@rescue_router.message(BotStates.rescue_waiting_photo, F.photo)
async def rescue_waiting_photo_handler(message: Message, state: FSMContext, bot: Bot):
    """Принять новое фото в rescue flow и запустить новый Take (is_rescue_photo_replace)."""
    data = await state.get_data()
    take_id = data.get("rescue_take_id")
    telegram_id = str(message.from_user.id) if message.from_user else None
    if telegram_id:
        try:
            with get_db_session() as db:
                user = UserService(db).get_by_telegram_id(telegram_id)
                if user:
                    ProductAnalyticsService(db).track(
                        "rescue_photo_uploaded",
                        user.id,
                        take_id=take_id,
                        properties={"button_id": "rescue_photo_uploaded", "take_id": take_id},
                    )
        except Exception:
            logger.exception("rescue_photo_uploaded track failed")
    photo = message.photo[-1]
    try:
        inputs_dir = os.path.join(settings.storage_base_path, "inputs")
        os.makedirs(inputs_dir, exist_ok=True)
        local_path = os.path.join(inputs_dir, f"rescue_{photo.file_id}.jpg")
        file = await bot.get_file(photo.file_id)
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
        ok = await _rescue_save_photo_and_start_take(message, bot, state, local_path, photo.file_id)
        if not ok:
            return
    except Exception:
        logger.exception("rescue_waiting_photo photo error")
        await message.answer("Не удалось сохранить фото. Попробуйте ещё раз.")
        return


@rescue_router.message(BotStates.rescue_waiting_photo, F.document)
async def rescue_waiting_photo_document(message: Message, state: FSMContext, bot: Bot):
    """Принять документ-изображение в rescue flow."""
    doc = message.document
    if not doc:
        await message.answer(t("errors.try_later_short", "Ошибка. Попробуйте позже."))
        return
    ext = _document_image_ext(doc.mime_type, doc.file_name)
    if not ext:
        await message.answer(t("flow.only_images", "Поддерживаются только изображения: JPG, PNG, WEBP. Отправьте файл с фото."))
        return
    data = await state.get_data()
    take_id = data.get("rescue_take_id")
    telegram_id = str(message.from_user.id) if message.from_user else None
    if telegram_id:
        try:
            with get_db_session() as db:
                user = UserService(db).get_by_telegram_id(telegram_id)
                if user:
                    ProductAnalyticsService(db).track(
                        "rescue_photo_uploaded",
                        user.id,
                        take_id=take_id,
                        properties={"button_id": "rescue_photo_uploaded", "take_id": take_id},
                    )
        except Exception:
            logger.exception("rescue_photo_uploaded track failed")
    try:
        inputs_dir = os.path.join(settings.storage_base_path, "inputs")
        os.makedirs(inputs_dir, exist_ok=True)
        local_path = os.path.join(inputs_dir, f"rescue_{doc.file_id}{ext}")
        file = await bot.get_file(doc.file_id)
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
        ok = await _rescue_save_photo_and_start_take(message, bot, state, local_path, doc.file_id)
        if not ok:
            return
    except Exception:
        logger.exception("rescue_waiting_photo document error")
        await message.answer("Не удалось сохранить файл. Попробуйте ещё раз.")
        return


@rescue_router.message(BotStates.rescue_waiting_photo)
async def rescue_waiting_photo_wrong_input(message: Message):
    """Не фото в rescue_waiting_photo."""
    await message.answer("📷 Отправьте фото (изображение). Поддерживаются JPG, PNG, WEBP.")
