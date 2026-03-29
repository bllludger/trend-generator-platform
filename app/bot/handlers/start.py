"""Handlers for /start command and subscription check."""
import logging
import os
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from app.bot.states import BotStates
from app.bot.helpers import (
    t, tr, get_db_session, _escape_markdown, _parse_start_raw_arg, _parse_start_arg,
    _parse_start_theme, _parse_referral_code, _parse_traffic_source, logger,
    _user_subscribed, _send_subscription_prompt,
)
from app.bot.keyboards import main_menu_keyboard, create_photo_only_keyboard, _subscription_keyboard
from app.bot.constants import (
    WELCOME_IMAGE_PATH, WELCOME_TEXT_DEFAULT, SUBSCRIPTION_CHANNEL_USERNAME,
    SUBSCRIPTION_CALLBACK, AFTER_SUBSCRIPTION_TEXT, SUBSCRIBE_TEXT_DEFAULT,
)
from app.core.config import settings
from app.services.users.service import UserService
from app.services.sessions.service import SessionService
from app.services.trends.service import TrendService
from app.services.themes.service import ThemeService
from app.services.audit.service import AuditService
from app.services.product_analytics.service import ProductAnalyticsService
from app.services.payments.service import PaymentService
from app.services.unlock_order.service import UnlockOrderService
from app.services.trial_bundle_order.service import TrialBundleOrderService
from app.services.trial_v2.service import TrialV2Service
from app.services.favorites.service import FavoriteService
from app.referral.service import ReferralService
from app.models.user import User
from app.utils.metrics import bot_started_total
from app.utils.telegram_photo import path_for_telegram_photo

start_router = Router()


@start_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Handle /start command. Supports deep links: /start trend_<id>, /start theme_<id>, /start ref_<code>."""
    telegram_id = str(message.from_user.id)
    u = message.from_user

    try:
        with get_db_session() as db:
            user_service = UserService(db)
            audit = AuditService(db)

            user_service.get_or_create_user(
                telegram_id,
                telegram_username=u.username,
                telegram_first_name=u.first_name,
                telegram_last_name=u.last_name,
            )
            user = user_service.get_by_telegram_id(telegram_id)
            session_svc = SessionService(db)
            analytics = ProductAnalyticsService(db)

            audit.log(
                actor_type="user",
                actor_id=telegram_id,
                action="start",
                entity_type="session",
                entity_id=None,
                payload={},
            )
            if user:
                active_session = session_svc.get_active_session(user.id)
                analytics.track_funnel_step(
                    "bot_started",
                    user.id,
                    session_id=active_session.id if active_session else None,
                    source_component="bot",
                    properties={"entry_point": "command_start"},
                )
                bot_started_total.inc()

            # Traffic source from ad deep link (?start=src_<slug> or src_<slug>_c_<campaign>)
            traffic_source_slug, traffic_campaign = _parse_traffic_source(message.text)
            if traffic_source_slug and user:
                audit.log(
                    actor_type="user",
                    actor_id=telegram_id,
                    action="traffic_start",
                    entity_type="user",
                    entity_id=user.id,
                    payload={
                        "traffic_source": traffic_source_slug,
                        "campaign": traffic_campaign,
                        "raw_param": _parse_start_raw_arg(message.text),
                    },
                )
                # First-touch: set source on user once (do not overwrite)
                if user.traffic_source is None:
                    user.traffic_source = traffic_source_slug
                    user.traffic_campaign = traffic_campaign
                ProductAnalyticsService(db).track(
                    "traffic_attribution",
                    user.id,
                    source=traffic_source_slug,
                    campaign_id=traffic_campaign,
                    properties={
                        "source": traffic_source_slug,
                        "campaign_id": traffic_campaign,
                    },
                )

            ref_code = _parse_referral_code(message.text)
            if ref_code and user:
                audit.log(
                    actor_type="user",
                    actor_id=telegram_id,
                    action="referral_start",
                    entity_type="user",
                    entity_id=user.id,
                    payload={"referrer_code": ref_code},
                )
                ref_svc = ReferralService(db)
                attributed = ref_svc.attribute(user, ref_code)
                if attributed:
                    audit.log(
                        actor_type="user",
                        actor_id=telegram_id,
                        action="referral_attributed",
                        entity_type="user",
                        entity_id=user.id,
                        payload={"referrer_code": ref_code},
                    )
                    referrer = db.query(User).filter(User.referral_code == ref_code).first()
                    ProductAnalyticsService(db).track(
                        "traffic_attribution",
                        user.id,
                        source="referral",
                        properties={
                            "source": "referral",
                            "referrer_user_id": referrer.id if referrer else None,
                        },
                    )

            # Обязательная подписка на канал для новых пользователей
            if SUBSCRIPTION_CHANNEL_USERNAME and user and not _user_subscribed(user):
                await state.clear()
                await state.update_data(
                    pending_start_arg=_parse_start_arg(message.text),
                    pending_theme_id=_parse_start_theme(message.text),
                    pending_ref_code=ref_code,
                    pending_traffic_source=traffic_source_slug,
                    pending_traffic_campaign=traffic_campaign,
                )
                kb = _subscription_keyboard()
                await _send_subscription_prompt(
                    message,
                    t("subscription.prompt", SUBSCRIBE_TEXT_DEFAULT),
                    kb,
                )
                logger.info("start_awaiting_subscription", extra={"user_id": telegram_id})
                return

            start_arg = _parse_start_arg(message.text)
            start_raw = _parse_start_raw_arg(message.text)
            if start_raw and start_raw.startswith("unlock_done_"):
                order_id = start_raw.replace("unlock_done_", "", 1).strip()
                if order_id:
                    unlock_svc = UnlockOrderService(db)
                    order = unlock_svc.get_by_id(order_id)
                    if order and str(order.telegram_user_id) == telegram_id:
                        if order.status == "delivered":
                            await message.answer(
                                "Оплата принята. Файл уже отправлен в чат.",
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(text="🔄 Получить фото снова", callback_data=f"unlock_resend:{order_id}")],
                                    [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
                                ]),
                            )
                            return
                        if order.status == "paid":
                            await message.answer(
                                "Оплата принята. Файл скоро придёт в чат.",
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
                                ]),
                            )
                            try:
                                from app.core.celery_app import celery_app as _celery
                                _celery.send_task(
                                    "app.workers.tasks.deliver_unlock.deliver_unlock_file",
                                    args=[order_id],
                                )
                            except Exception:
                                pass
                            return
                        if order.status == "payment_pending":
                            await message.answer(
                                "Ожидаем подтверждение оплаты. Если вы уже оплатили — нажмите «Проверить оплату».",
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(text="♻️ Проверить оплату", callback_data=f"unlock_check:{order_id}")],
                                    [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
                                ]),
                            )
                            return
                        if order.status in ("canceled", "failed", "delivery_failed"):
                            await message.answer(
                                "Этот заказ отменён или завершён с ошибкой. Можно оформить новый — выберите вариант в чате с ботом.",
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
                                ]),
                            )
                            return
                    elif order_id:
                        await message.answer("Заказ не найден или не принадлежит вам.", reply_markup=main_menu_keyboard())
                        return
                else:
                    await message.answer("Неверная ссылка. Используйте меню бота.", reply_markup=main_menu_keyboard())
                return
            if start_raw and start_raw.startswith("pack_done_"):
                order_id = start_raw.replace("pack_done_", "", 1).strip()
                if order_id:
                    from app.services.pack_order.service import PackOrderService
                    pack_order_svc = PackOrderService(db)
                    pack_order = pack_order_svc.get_by_id(order_id)
                    if pack_order and str(pack_order.telegram_user_id) == telegram_id:
                        if pack_order.status == "completed":
                            from app.bot.handlers.results import _send_pack_activated_post
                            pack = PaymentService(db).get_pack(pack_order.pack_id)
                            pack_emoji = getattr(pack, "emoji", "") if pack else ""
                            pack_name = getattr(pack, "name", pack_order.pack_id) if pack else str(pack_order.pack_id)
                            session_svc = SessionService(db)
                            user = UserService(db).get_by_telegram_id(telegram_id)
                            remaining = 0
                            if user:
                                session = session_svc.get_active_session(user.id)
                                if session:
                                    remaining = (session.takes_limit or 0) - (session.takes_used or 0)
                            await _send_pack_activated_post(
                                message,
                                db=db,
                                telegram_id=telegram_id,
                                pack_emoji=pack_emoji,
                                pack_name=pack_name,
                                remaining_display=remaining,
                            )
                            return
                        if pack_order.status == "paid":
                            await message.answer(
                                "Оплата принята. Пакет активируется — обычно это несколько секунд.\n\n"
                                "Если сообщение не пришло, нажмите «Проверить оплату».",
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(text="♻️ Проверить оплату", callback_data=f"pack_check:{order_id}")],
                                    [InlineKeyboardButton(text="🛟 Помощь", callback_data="profile:support")],
                                ]),
                            )
                            return
                        if pack_order.status == "payment_pending":
                            await message.answer(
                                "Платёж обрабатывается.\n\n"
                                "Обычно это занимает несколько секунд.\n"
                                "Пакет активируется автоматически.\n\n"
                                "Если прошло больше минуты — нажмите «Помощь».",
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(text="♻️ Проверить оплату", callback_data=f"pack_check:{order_id}")],
                                    [InlineKeyboardButton(text="🛟 Помощь", callback_data="profile:support")],
                                ]),
                            )
                            return
                        if pack_order.status in ("canceled", "failed"):
                            await message.answer(
                                "⚠️ Платёж не был завершён.\n\n"
                                "Деньги не списаны.\n\n"
                                "Можно оформить новый заказ и выбрать тариф заново.",
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(text="💵 Выбрать тариф", callback_data="shop:open")],
                                    [InlineKeyboardButton(text="🛟 Помощь", callback_data="profile:support")],
                                ]),
                            )
                            return
                    elif order_id:
                        await message.answer("Заказ не найден или не принадлежит вам.", reply_markup=main_menu_keyboard())
                        return
                else:
                    await message.answer("Неверная ссылка. Используйте меню бота.", reply_markup=main_menu_keyboard())
                return
            if start_raw and start_raw.startswith("trial_bundle_done_"):
                order_id = start_raw.replace("trial_bundle_done_", "", 1).strip()
                if order_id:
                    bundle_svc = TrialBundleOrderService(db)
                    order = bundle_svc.get_by_id(order_id)
                    if order and str(order.telegram_user_id) == telegram_id:
                        if order.status == "delivered":
                            await message.answer(
                                "Оплата подтверждена. Все 3 фото уже отправлены в чат.",
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
                                ]),
                            )
                            return
                        if order.status in ("paid", "payment_pending", "created"):
                            await message.answer(
                                "Проверяем оплату bundle и отправляем все 3 фото.",
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(text="♻️ Проверить оплату", callback_data=f"trial_bundle_check:{order.id}")],
                                    [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
                                ]),
                            )
                            return
                        if order.status == "delivery_failed":
                            await message.answer(
                                "Платёж подтверждён, но доставка не завершилась. Повторите отправку.",
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(text="🔄 Повторить отправку", callback_data=f"trial_bundle_check:{order.id}")],
                                    [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
                                ]),
                            )
                            return
                        if order.status in ("canceled", "failed"):
                            await message.answer(
                                "Платёж не завершён. Можно оформить заказ заново.",
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
                                ]),
                            )
                            return
                    await message.answer("Заказ не найден или не принадлежит вам.", reply_markup=main_menu_keyboard())
                    return
                await message.answer("Неверная ссылка. Используйте меню бота.", reply_markup=main_menu_keyboard())
                return
            if start_arg:
                trend_service = TrendService(db)
                trend = trend_service.get(start_arg)
                if trend and trend.enabled:
                    await state.clear()
                    await state.update_data(
                        selected_trend_id=trend.id,
                        selected_trend_name=trend.name,
                    )
                    await state.set_state(BotStates.waiting_for_photo)
                    msg_text = tr(
                        "start.deeplink_trend",
                        "Отправьте фото — применим тренд «{name}»",
                        name=trend.name,
                    )
                    await message.answer(msg_text, reply_markup=main_menu_keyboard())
                    logger.info("start_deeplink_trend", extra={"user_id": telegram_id, "trend_id": trend.id})
                    return

            # Диплинк на тематику (для рассылок): после выбора пола и фото откроется эта тематика
            theme_arg = _parse_start_theme(message.text)

        await state.clear()
        if theme_arg:
            with get_db_session() as db:
                theme_service = ThemeService(db)
                theme = theme_service.get(theme_arg)
                if theme and theme.enabled:
                    await state.update_data(preselected_theme_id=theme.id)
                    logger.info("start_deeplink_theme", extra={"user_id": telegram_id, "theme_id": theme.id})
        welcome_text = t("start.welcome_text", WELCOME_TEXT_DEFAULT)
        welcome_sent = False
        if os.path.exists(WELCOME_IMAGE_PATH):
            try:
                photo_path, is_temp = path_for_telegram_photo(WELCOME_IMAGE_PATH)
                await message.answer_photo(
                    photo=FSInputFile(photo_path),
                    caption=welcome_text,
                    reply_markup=main_menu_keyboard(),
                )
                welcome_sent = True
                if is_temp and os.path.isfile(photo_path):
                    try:
                        os.unlink(photo_path)
                    except OSError:
                        pass
            except Exception as e:
                logger.warning("start_welcome_photo_failed", extra={"path": WELCOME_IMAGE_PATH, "error": str(e)})
        if not welcome_sent:
            if not os.path.exists(WELCOME_IMAGE_PATH):
                logger.warning("start_welcome_image_not_found", extra={"path": WELCOME_IMAGE_PATH})
            await message.answer(welcome_text, reply_markup=main_menu_keyboard())
        logger.info("start", extra={"user_id": telegram_id})
    except Exception:
        logger.exception("Error in cmd_start", extra={"user_id": telegram_id})
        try:
            await message.answer(
                t("start.welcome_text", WELCOME_TEXT_DEFAULT),
                reply_markup=main_menu_keyboard(),
            )
        except Exception:
            await message.answer(t("errors.try_later", "Произошла ошибка. Попробуйте позже."))


@start_router.callback_query(F.data == SUBSCRIPTION_CALLBACK)
async def subscription_check(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Проверка подписки на канал и продолжение стартового сценария."""
    telegram_id = str(callback.from_user.id)
    try:
        chat_id = f"@{SUBSCRIPTION_CHANNEL_USERNAME}"
        member = await bot.get_chat_member(chat_id=chat_id, user_id=callback.from_user.id)
        status = (getattr(member, "status", None) or "").lower() if hasattr(member, "status") else ""
        if status not in ("member", "administrator", "creator"):
            await callback.answer(
                t("subscription.not_subscribed", "Сначала подпишитесь на канал, затем нажмите «Я подписался»."),
                show_alert=True,
            )
            return

        # Remove the old subscription prompt block (image/text + inline buttons)
        # before sending the post-subscription success screen.
        try:
            await callback.message.delete()
        except Exception:
            pass

        data = await state.get_data()
        pending_start_arg = data.get("pending_start_arg")
        pending_theme_id = data.get("pending_theme_id")
        pending_traffic_source = data.get("pending_traffic_source")
        pending_traffic_campaign = data.get("pending_traffic_campaign")
        await state.clear()

        with get_db_session() as db:
            user_service = UserService(db)
            user = user_service.get_by_telegram_id(telegram_id)
            if user:
                flags = dict(user.flags or {})
                flags["subscribed_examples_channel"] = True
                user.flags = flags
                if pending_traffic_source and user.traffic_source is None:
                    user.traffic_source = pending_traffic_source
                    user.traffic_campaign = pending_traffic_campaign
                    audit_svc = AuditService(db)
                    audit_svc.log(
                        actor_type="user",
                        actor_id=telegram_id,
                        action="traffic_start",
                        entity_type="user",
                        entity_id=user.id,
                        payload={
                            "traffic_source": pending_traffic_source,
                            "campaign": pending_traffic_campaign,
                            "after_subscription": True,
                        },
                    )

        # Продолжаем как после /start: диплинк тренда, диплинк тематики или приветствие
        with get_db_session() as db:
            if pending_start_arg:
                trend_service = TrendService(db)
                trend = trend_service.get(pending_start_arg)
                if trend and trend.enabled:
                    await state.update_data(
                        selected_trend_id=trend.id,
                        selected_trend_name=trend.name,
                    )
                    await state.set_state(BotStates.waiting_for_photo)
                    msg_text = tr(
                        "start.deeplink_trend",
                        "Отправьте фото — применим тренд «{name}»",
                        name=trend.name,
                    )
                    await callback.message.answer(msg_text, reply_markup=main_menu_keyboard())
                    await callback.answer(t("subscription.done", "Спасибо! Добро пожаловать."))
                    return
            if pending_theme_id:
                theme_service = ThemeService(db)
                theme = theme_service.get(pending_theme_id)
                if theme and theme.enabled:
                    await state.update_data(preselected_theme_id=theme.id)
                    logger.info("start_deeplink_theme_after_subscription", extra={"user_id": telegram_id, "theme_id": theme.id})

        after_text = t("subscription.after_done", AFTER_SUBSCRIPTION_TEXT)
        after_sent = False
        sent_msg = None
        if os.path.exists(WELCOME_IMAGE_PATH):
            try:
                photo_path, is_temp = path_for_telegram_photo(WELCOME_IMAGE_PATH)
                sent_msg = await callback.message.answer_photo(
                    photo=FSInputFile(photo_path),
                    caption=after_text,
                    reply_markup=create_photo_only_keyboard(),
                )
                after_sent = True
                if is_temp and os.path.isfile(photo_path):
                    try:
                        os.unlink(photo_path)
                    except OSError:
                        pass
            except Exception as e:
                logger.warning("subscription_after_photo_failed", extra={"path": WELCOME_IMAGE_PATH, "error": str(e)})
        if not after_sent:
            sent_msg = await callback.message.answer(after_text, reply_markup=create_photo_only_keyboard())
        if sent_msg:
            await state.update_data(after_subscription_message_id=sent_msg.message_id)
        await callback.answer(t("subscription.done", "Спасибо! Добро пожаловать."))
    except Exception as e:
        logger.exception("subscription_check error", extra={"user_id": telegram_id})
        await callback.answer(t("errors.try_later", "Произошла ошибка. Попробуйте позже."), show_alert=True)
