import logging
import os

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    FSInputFile, LabeledPrice,
)
from aiogram.fsm.context import FSMContext

from app.bot.states import BotStates
from app.bot.helpers import t, tr, get_db_session, _escape_markdown, logger
from app.bot.keyboards import main_menu_keyboard, _payment_method_keyboard, audience_keyboard, themes_keyboard
from app.bot.constants import MONEY_IMAGE_PATH
from app.core.config import settings
from app.services.users.service import UserService
from app.services.sessions.service import SessionService
from app.services.takes.service import TakeService
from app.services.payments.service import PaymentService, PRODUCT_LADDER_IDS
from app.services.themes.service import ThemeService
from app.services.trends.service import TrendService
from app.services.favorites.service import FavoriteService
from app.services.hd_balance.service import HDBalanceService
from app.services.audit.service import AuditService
from app.services.product_analytics.service import ProductAnalyticsService
from app.services.unlock_order.service import UnlockOrderService, unlock_photo_display_filename
from app.services.idempotency import IdempotencyStore
from app.services.yookassa.client import YooKassaClient, YooKassaClientError
from app.services.balance_tariffs import build_balance_tariffs_message, get_balance_line, _pack_outcome_label
from app.bot.handlers.favorites import _select_hd_favorites_with_bundle_budget
from app.models.user import User
from app.models.pack import Pack
from app.models.session import Session as SessionModel
from app.models.take import Take as TakeModel
from app.utils.metrics import pay_initiated_total, pay_success_total, paywall_viewed_total
from app.utils.currency import format_stars_rub
from app.utils.telegram_photo import path_for_telegram_photo

session_router = Router()


async def _send_last_take_previews_for_choice(callback: CallbackQuery, take_id: str, previews: list[tuple[str, str]]) -> None:
    """Fallback: вернуть последний набор превью (A/B/C), если нет сохранённого выбора."""
    for variant, preview_path in previews:
        await callback.message.answer_photo(
            photo=FSInputFile(preview_path),
            caption=f"Вариант {variant}",
        )
    await callback.message.answer(
        "У вас нет сохранённого выбора. Выберите вариант из последнего набора:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="1️⃣ Выбрать первый вариант", callback_data=f"choose:{take_id}:A")],
            [InlineKeyboardButton(text="2️⃣ Выбрать второй вариант", callback_data=f"choose:{take_id}:B")],
            [InlineKeyboardButton(text="3️⃣ Выбрать третий вариант", callback_data=f"choose:{take_id}:C")],
            [InlineKeyboardButton(text="🔁 Все 3 не подходят", callback_data=f"rescue:reject_set:{take_id}")],
        ]),
    )


async def _replace_step_message(message: Message, text: str, reply_markup=None) -> None:
    """Replace current bot step message to avoid chat noise."""
    try:
        if getattr(message, "text", None) is not None:
            await message.edit_text(text, reply_markup=reply_markup)
            return
        if getattr(message, "caption", None) is not None:
            await message.edit_caption(caption=text, reply_markup=reply_markup)
            return
    except Exception:
        pass
    await message.answer(text, reply_markup=reply_markup)


@session_router.callback_query(F.data == "post_hd:create")
async def post_hd_create_photo(callback: CallbackQuery, state: FSMContext):
    """После выдачи 4K: быстрый переход к созданию нового фото."""
    await state.clear()
    await state.set_state(BotStates.waiting_for_audience)
    await callback.message.answer(
        t("audience.prompt", "Для кого фотосессия?"),
        reply_markup=audience_keyboard(),
    )
    await callback.answer()


@session_router.callback_query(F.data == "post_hd:trends")
async def post_hd_back_to_trends(callback: CallbackQuery, state: FSMContext):
    """После выдачи 4K: вернуть к выбору трендов по последнему входному фото."""
    telegram_id = str(callback.from_user.id)
    try:
        with get_db_session() as db:
            user = UserService(db).get_or_create_user(
                telegram_id,
                telegram_username=callback.from_user.username,
                telegram_first_name=callback.from_user.first_name,
                telegram_last_name=callback.from_user.last_name,
            )
            last_take = (
                db.query(TakeModel)
                .filter(
                    TakeModel.user_id == user.id,
                    TakeModel.status.in_(["ready", "partial_fail"]),
                )
                .order_by(TakeModel.created_at.desc())
                .first()
            )
            if not last_take or not isinstance(last_take.input_local_paths, list) or not last_take.input_local_paths:
                await callback.answer("Нет исходного фото — начните новый сценарий.", show_alert=True)
                await state.clear()
                await state.set_state(BotStates.waiting_for_audience)
                await callback.message.answer(
                    t("audience.prompt", "Для кого фотосессия?"),
                    reply_markup=audience_keyboard(),
                )
                return

            photo_local_path = last_take.input_local_paths[0]
            photo_file_id = (last_take.input_file_ids or [None])[0]
            if not photo_local_path or not os.path.exists(photo_local_path):
                await callback.answer("Исходное фото недоступно. Загрузите новое.", show_alert=True)
                await state.clear()
                await state.set_state(BotStates.waiting_for_audience)
                await callback.message.answer(
                    t("audience.prompt", "Для кого фотосессия?"),
                    reply_markup=audience_keyboard(),
                )
                return

            audience = None
            if last_take.trend_id:
                trend = TrendService(db).get(last_take.trend_id)
                targets = getattr(trend, "target_audiences", None) if trend else None
                if isinstance(targets, list) and targets:
                    raw = str(targets[0] or "").strip().lower()
                    if raw:
                        audience = raw
            if not audience:
                await callback.answer("Не удалось определить аудиторию, выберите вручную.", show_alert=True)
                await state.clear()
                await state.set_state(BotStates.waiting_for_audience)
                await callback.message.answer(
                    t("audience.prompt", "Для кого фотосессия?"),
                    reply_markup=audience_keyboard(),
                )
                return
            theme_ids_with_trends = TrendService(db).list_theme_ids_with_active_trends(audience)
            all_themes = ThemeService(db).list_all()
            themes = [x for x in all_themes if x.enabled and x.id in theme_ids_with_trends]
            if not themes:
                await callback.answer("Тренды временно недоступны", show_alert=True)
                return
            themes_data = [{"id": x.id, "name": x.name, "emoji": x.emoji or ""} for x in themes]

            await state.clear()
            await state.update_data(
                photo_file_id=photo_file_id,
                photo_local_path=photo_local_path,
                selected_trend_id=None,
                selected_trend_name=None,
                custom_prompt=None,
                audience_type=audience,
            )
            await state.set_state(BotStates.waiting_for_trend)
            await callback.message.answer(
                t("flow.photo_accepted_choose_theme", "Теперь выберите стиль 👇"),
                reply_markup=themes_keyboard(themes_data),
            )
            await callback.answer()
    except Exception:
        logger.exception("post_hd_back_to_trends_error", extra={"user_id": telegram_id})
        await callback.answer("Ошибка. Попробуйте позже.", show_alert=True)


@session_router.callback_query(F.data.startswith("unlock_check:"))
async def unlock_check_callback(callback: CallbackQuery):
    """Второй контур: проверить оплату по YooKassa GET /payments/{id} и при успехе поставить доставку."""
    telegram_id = str(callback.from_user.id)
    parts = callback.data.split(":", 1)
    if len(parts) != 2:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    order_id = (parts[1] or "").strip()
    if not order_id:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    lock_store = None
    lock_acquired = False
    lock_key = f"unlock_check:{telegram_id}:{order_id}"
    try:
        try:
            lock_store = IdempotencyStore()
            lock_acquired = lock_store.check_and_set(lock_key, ttl_seconds=30)
            if not lock_acquired:
                await callback.answer("⏳ Проверка уже выполняется")
                return
        except Exception as e:
            logger.warning("unlock_check_lock_unavailable", extra={"user_id": telegram_id, "order_id": order_id, "error": str(e)})

        with get_db_session() as db:
            unlock_svc = UnlockOrderService(db)
            order = unlock_svc.get_by_id(order_id)
            if not order or str(order.telegram_user_id) != telegram_id:
                await callback.answer("Заказ не найден", show_alert=True)
                return
            user = UserService(db).get_by_telegram_id(telegram_id)
            if user:
                try:
                    ProductAnalyticsService(db).track(
                        "button_click",
                        user.id,
                        properties={"button_id": "unlock_check", "order_id": order_id},
                    )
                except Exception:
                    logger.exception("button_click track failed unlock_check")
            if order.status == "delivered":
                await callback.answer("Оплата уже подтверждена")
                await _replace_step_message(callback.message, "Оплата уже подтверждена. Файл отправлен или скоро придёт.")
                return
            if order.status in ("paid", "delivery_failed"):
                from app.core.celery_app import celery_app as _celery
                try:
                    _celery.send_task(
                        "app.workers.tasks.deliver_unlock.deliver_unlock_file",
                        args=[order.id],
                    )
                except Exception:
                    logger.exception("unlock_check_enqueue_failed_after_paid", extra={"user_id": telegram_id, "order_id": order_id})
                    await callback.answer("Оплата подтверждена, но запуск доставки временно недоступен.", show_alert=True)
                    await _replace_step_message(
                        callback.message,
                        "Оплата подтверждена.\n\n"
                        "Сейчас не удалось запустить доставку файла.\n"
                        "Нажмите «Проверить оплату» ещё раз через несколько секунд.",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="♻️ Проверить оплату", callback_data=f"unlock_check:{order_id}")],
                            [InlineKeyboardButton(text="🛟 Помощь", callback_data="profile:support")],
                        ]),
                    )
                    return
                await callback.answer("Оплата подтверждена, файл отправляется")
                await _replace_step_message(callback.message, "Оплата подтверждена. Файл скоро придёт в чат.")
                return
            if order.status != "payment_pending" or not order.yookassa_payment_id:
                await callback.answer("Нечего проверять", show_alert=True)
                return
            yookassa = YooKassaClient()
            payment = yookassa.get_payment(order.yookassa_payment_id) if yookassa.is_configured() else None
            if payment and (payment.get("status") or "") == "succeeded":
                unlock_svc.mark_paid(order_id=order.id)
                try:
                    PaymentService(db).record_yookassa_unlock_payment(order)
                except Exception:
                    logger.warning("unlock_check_record_payment_failed", extra={"user_id": telegram_id, "order_id": order_id})
                db.commit()
                from app.core.celery_app import celery_app as _celery
                try:
                    _celery.send_task(
                        "app.workers.tasks.deliver_unlock.deliver_unlock_file",
                        args=[order.id],
                    )
                except Exception:
                    logger.exception("unlock_check_enqueue_failed_after_mark_paid", extra={"user_id": telegram_id, "order_id": order_id})
                    await callback.answer("Оплата подтверждена, но запуск доставки временно недоступен.", show_alert=True)
                    await _replace_step_message(
                        callback.message,
                        "Оплата подтверждена.\n\n"
                        "Сейчас не удалось запустить доставку файла.\n"
                        "Нажмите «Проверить оплату» ещё раз через несколько секунд.",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="♻️ Проверить оплату", callback_data=f"unlock_check:{order_id}")],
                            [InlineKeyboardButton(text="🛟 Помощь", callback_data="profile:support")],
                        ]),
                    )
                    return
                await callback.answer("Оплата подтверждена, файл отправляется")
                await _replace_step_message(callback.message, "Оплата подтверждена. Файл скоро придёт в чат.")
            else:
                await callback.answer("Оплата пока не поступила. Попробуйте позже.")
                await _replace_step_message(callback.message, "🙁\nОплата пока не поступила. Подождите или попробуйте позже.")
    except Exception:
        logger.exception("unlock_check_callback error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)
    finally:
        if lock_store is not None and lock_acquired:
            try:
                lock_store.release(lock_key)
            except Exception:
                logger.warning("unlock_check_lock_release_failed", extra={"user_id": telegram_id, "order_id": order_id})


@session_router.callback_query(F.data.startswith("pack_check:"))
async def pack_check_callback(callback: CallbackQuery):
    """Проверить оплату пакета по ЮKassa и при успехе активировать пакет и показать поздравление."""
    telegram_id = str(callback.from_user.id)
    parts = callback.data.split(":", 1)
    if len(parts) != 2:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    order_id = (parts[1] or "").strip()
    if not order_id:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    lock_store = None
    lock_acquired = False
    lock_key = f"pack_check:{telegram_id}:{order_id}"
    try:
        try:
            lock_store = IdempotencyStore()
            lock_acquired = lock_store.check_and_set(lock_key, ttl_seconds=30)
            if not lock_acquired:
                await callback.answer("⏳ Проверка уже выполняется")
                return
        except Exception as e:
            logger.warning("pack_check_lock_unavailable", extra={"user_id": telegram_id, "order_id": order_id, "error": str(e)})

        with get_db_session() as db:
            from app.services.pack_order.service import PackOrderService
            pack_order_svc = PackOrderService(db)
            pack_order = pack_order_svc.get_by_id(order_id)
            if not pack_order or str(pack_order.telegram_user_id) != telegram_id:
                await callback.answer("Заказ не найден", show_alert=True)
                return
            user = UserService(db).get_by_telegram_id(telegram_id)
            if user:
                try:
                    ProductAnalyticsService(db).track(
                        "button_click",
                        user.id,
                        properties={"button_id": "pack_check", "order_id": order_id},
                    )
                except Exception:
                    logger.exception("button_click track failed pack_check")
            if pack_order.status == "completed":
                from app.bot.handlers.results import _send_pack_activated_post
                pack = PaymentService(db).get_pack(pack_order.pack_id)
                pack_emoji = getattr(pack, "emoji", "") if pack else ""
                pack_name = getattr(pack, "name", pack_order.pack_id) if pack else str(pack_order.pack_id)
                user = UserService(db).get_by_telegram_id(telegram_id)
                remaining = 0
                if user:
                    session = SessionService(db).get_active_session(user.id)
                    if session:
                        remaining = (session.takes_limit or 0) - (session.takes_used or 0)
                try:
                    await callback.message.delete()
                except Exception:
                    pass
                await callback.answer("Пакет уже активирован")
                await _send_pack_activated_post(
                    callback.message,
                    db=db,
                    telegram_id=telegram_id,
                    pack_emoji=pack_emoji,
                    pack_name=pack_name,
                    remaining_display=remaining,
                )
                return
            if pack_order.status not in ("payment_pending", "paid") or not pack_order.yookassa_payment_id:
                await callback.answer("Нечего проверять", show_alert=True)
                return
            yookassa = YooKassaClient()
            payment = yookassa.get_payment(pack_order.yookassa_payment_id) if yookassa.is_configured() else None
            payment_status = (payment.get("status") or "") if payment else ""
            if payment_status in ("canceled", "failed"):
                pack_order_svc.mark_canceled(order_id=pack_order.id) if payment_status == "canceled" else pack_order_svc.mark_failed(order_id=pack_order.id)
                await callback.answer("Платёж не прошёл")
                await _replace_step_message(
                    callback.message,
                    "⚠️ Платёж не был завершён.\n\n"
                    "Деньги не списаны.\n\n"
                    "Можно оформить новый заказ и выбрать тариф заново.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💵 Выбрать тариф", callback_data="shop:open")],
                        [InlineKeyboardButton(text="🛟 Помощь", callback_data="profile:support")],
                    ]),
                )
                return
            if payment and payment_status == "succeeded":
                payment_svc = PaymentService(db)
                if pack_order.status in ("created", "payment_pending"):
                    pack_order_svc.mark_paid(order_id=pack_order.id)
                payment_obj, session, trial_err, _ = payment_svc.process_session_purchase_yookassa_link(
                    telegram_user_id=telegram_id,
                    pack_id=pack_order.pack_id,
                    yookassa_payment_id=pack_order.yookassa_payment_id,
                    amount_kopecks=pack_order.amount_kopecks,
                )
                if payment_obj and session:
                    pack_order_svc.mark_completed(pack_order.id)
                    from app.bot.handlers.results import _send_pack_activated_post
                    pack = payment_svc.get_pack(pack_order.pack_id)
                    pack_emoji = getattr(pack, "emoji", "") if pack else ""
                    pack_name = getattr(pack, "name", pack_order.pack_id) if pack else str(pack_order.pack_id)
                    remaining = (session.takes_limit or 0) - (session.takes_used or 0)
                    try:
                        await callback.message.delete()
                    except Exception:
                        pass
                    await callback.answer("Оплата подтверждена")
                    await _send_pack_activated_post(
                        callback.message,
                        db=db,
                        telegram_id=telegram_id,
                        pack_emoji=pack_emoji,
                        pack_name=pack_name,
                        remaining_display=remaining,
                    )
                else:
                    await callback.answer("Ошибка активации", show_alert=True)
                    await _replace_step_message(
                        callback.message,
                        "При активации пакета произошла ошибка. Обратитесь в поддержку — мы поможем завершить активацию.",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="🛟 Помощь", callback_data="profile:support")],
                            [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
                        ]),
                    )
            else:
                await callback.answer("Платёж ещё обрабатывается")
                pending_rows = [
                    [InlineKeyboardButton(text="♻️ Проверить оплату", callback_data=f"pack_check:{order_id}")],
                ]
                confirmation_url = (getattr(pack_order, "confirmation_url", None) or "").strip()
                if confirmation_url:
                    pending_rows.append([InlineKeyboardButton(text="💵 Оплатить снова", url=confirmation_url)])
                pending_rows.append([InlineKeyboardButton(text="🛟 Помощь", callback_data="profile:support")])
                await _replace_step_message(
                    callback.message,
                    "Платёж ещё обрабатывается.\n\n"
                    "Пакет активируется автоматически после подтверждения.\n\n"
                    "Если прошло больше минуты — нажмите «Помощь».",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=pending_rows),
                )
    except Exception:
        logger.exception("pack_check_callback error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)
    finally:
        if lock_store is not None and lock_acquired:
            try:
                lock_store.release(lock_key)
            except Exception:
                logger.warning("pack_check_lock_release_failed", extra={"user_id": telegram_id, "order_id": order_id})


@session_router.callback_query(F.data.startswith("deliver_hd_one:"))
async def deliver_hd_one_callback(callback: CallbackQuery, state: FSMContext):
    """Deliver 4K for one favorite (short path after choosing variant)."""
    telegram_id = str(callback.from_user.id)
    parts = callback.data.split(":", 1)
    if len(parts) != 2:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    fav_id = parts[1]
    fallback_take_id: str | None = None
    fallback_previews: list[tuple[str, str]] = []
    try:
        with get_db_session() as db:
            user_service = UserService(db)
            user = user_service.get_or_create_user(
                telegram_id,
                telegram_username=callback.from_user.username,
                telegram_first_name=callback.from_user.first_name,
                telegram_last_name=callback.from_user.last_name,
            )
            fav_svc = FavoriteService(db)
            hd_svc = HDBalanceService(db)
            fav = fav_svc.get_favorite(fav_id)
            if not fav or str(fav.user_id) != str(user.id):
                last_take = (
                    db.query(TakeModel)
                    .filter(
                        TakeModel.user_id == user.id,
                        TakeModel.status.in_(["ready", "partial_fail"]),
                    )
                    .order_by(TakeModel.created_at.desc())
                    .first()
                )
                if not last_take:
                    await callback.answer("❌ Избранное не найдено", show_alert=True)
                    return
                candidate = [
                    ("A", getattr(last_take, "variant_a_preview", None)),
                    ("B", getattr(last_take, "variant_b_preview", None)),
                    ("C", getattr(last_take, "variant_c_preview", None)),
                ]
                fallback_previews = [
                    (v, p) for v, p in candidate if isinstance(p, str) and p and os.path.exists(p)
                ]
                if not fallback_previews:
                    await callback.answer("❌ Нет доступных превью", show_alert=True)
                    return
                fallback_take_id = str(last_take.id)
            if fallback_take_id:
                # Показываем последний набор превью для нового выбора вместо ошибки.
                pass
            else:
                if fav.hd_status != "none":
                    await callback.answer("4K уже выдан или в обработке", show_alert=True)
                    return
                take_obj = db.query(TakeModel).filter(TakeModel.id == fav.take_id).one_or_none()
                charge_needed = not bool(getattr(take_obj, "hd_bundle_charged", False)) if take_obj else True
                balance = hd_svc.get_balance(user)
                if charge_needed and balance.get("total", 0) < 1:
                    await callback.answer("❌ Недостаточно доступа. Купите пакет.", show_alert=True)
                    return

        if fallback_take_id:
            await _send_last_take_previews_for_choice(callback, fallback_take_id, fallback_previews)
            await callback.answer("Показываю последний набор превью")
            return

        from app.core.celery_app import celery_app as _celery

        chat_id = str(callback.message.chat.id)
        source_message_id = callback.message.message_id
        status_msg = await callback.message.answer("⏳ Ожидайте файл в чате.")
        try:
            _celery.send_task(
                "app.workers.tasks.deliver_hd.deliver_hd",
                args=[fav_id],
                kwargs={
                    "status_chat_id": chat_id,
                    "status_message_id": status_msg.message_id,
                    "cleanup_message_ids": [source_message_id],
                    "suppress_post_upsell": True,
                },
            )
        except Exception:
            try:
                await status_msg.delete()
            except Exception:
                pass
            raise
        await callback.answer("🖼 Запущена выдача 4K")
    except Exception:
        logger.exception("deliver_hd_one_callback error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)


@session_router.callback_query(F.data == "deliver_hd")
async def deliver_hd_callback(callback: CallbackQuery, state: FSMContext):
    """Deliver 4K for all pending favorites."""
    telegram_id = str(callback.from_user.id)
    try:
        with get_db_session() as db:
            user_service = UserService(db)
            user = user_service.get_or_create_user(
                telegram_id,
                telegram_username=callback.from_user.username,
                telegram_first_name=callback.from_user.first_name,
                telegram_last_name=callback.from_user.last_name,
            )
            fav_svc = FavoriteService(db)
            hd_svc = HDBalanceService(db)

            favorites = fav_svc.list_favorites_for_user(user.id)
            pending = [f for f in favorites if f.hd_status == "none"]

            if not pending:
                await callback.answer("Нет избранных для 4K", show_alert=True)
                return

            balance = hd_svc.get_balance(user)
            pending_ids = _select_hd_favorites_with_bundle_budget(
                db,
                pending,
                int(balance.get("total", 0) or 0),
            )
            if not pending_ids:
                await callback.answer("❌ Недостаточно доступа. Купите пакет.", show_alert=True)
                return

        from app.core.celery_app import celery_app as _celery

        chat_id = str(callback.message.chat.id)
        source_message_id = callback.message.message_id
        launched = len(pending_ids)
        status_msg = await callback.message.answer(f"⏳ 4K выдача запущена для {launched} избранных. Ожидайте файлы...")
        try:
            for idx, fav_id in enumerate(pending_ids):
                kwargs = {
                    "status_chat_id": chat_id,
                    "suppress_post_upsell": True,
                }
                if idx == 0:
                    kwargs["status_message_id"] = status_msg.message_id
                    kwargs["cleanup_message_ids"] = [source_message_id]
                _celery.send_task(
                    "app.workers.tasks.deliver_hd.deliver_hd",
                    args=[fav_id],
                    kwargs=kwargs,
                )
        except Exception:
            try:
                await status_msg.delete()
            except Exception:
                pass
            raise

        await callback.answer(f"🖼 Запущена 4K выдача ({launched} шт.)")
    except Exception:
        logger.exception("deliver_hd_callback error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)


@session_router.callback_query(F.data == "session_status")
async def session_status(callback: CallbackQuery, state: FSMContext):
    """Show session status screen."""
    telegram_id = str(callback.from_user.id)
    try:
        with get_db_session() as db:
            user_service = UserService(db)
            user = user_service.get_or_create_user(
                telegram_id,
                telegram_username=callback.from_user.username,
                telegram_first_name=callback.from_user.first_name,
                telegram_last_name=callback.from_user.last_name,
            )
            try:
                ProductAnalyticsService(db).track("button_click", user.id, properties={"button_id": "session_status"})
            except Exception:
                logger.exception("button_click track failed session_status")
            session_svc = SessionService(db)
            hd_svc = HDBalanceService(db)
            fav_svc = FavoriteService(db)

            session = session_svc.get_active_session(user.id)
            balance = hd_svc.get_balance(user)

            if not session:
                await callback.message.answer(
                    "Нет активного пакета. Купите пакет, чтобы начать!",
                    reply_markup=main_menu_keyboard(),
                )
                await callback.answer()
                return

            fav_count = fav_svc.count_favorites(session.id)
            remaining = int(balance.get("total", 0) or 0)
            is_collection = session_svc.is_collection(session)
            hd_rem = session_svc.hd_remaining(session)
            selected_count = fav_svc.count_selected_for_hd(session.id)
            pack_id = session.pack_id
            takes_used = session.takes_used
            takes_limit = session.hd_limit or session.takes_limit
            hd_limit = session.hd_limit

        buttons = []
        if remaining > 0:
            buttons.append([InlineKeyboardButton(text="📸 Ещё фото", callback_data="take_more")])
        buttons.append([InlineKeyboardButton(text="⭐ Открыть избранное", callback_data="open_favorites")])

        if is_collection and selected_count > 0:
            buttons.append([InlineKeyboardButton(
                text=f"🖼 Забрать 4K альбомом ({selected_count})",
                callback_data="deliver_hd_album",
            )])
        elif fav_count > 0 and balance["total"] > 0:
            buttons.append([InlineKeyboardButton(text="🖼 Забрать 4K", callback_data="deliver_hd")])

        if pack_id == "trial":
            buttons.append([InlineKeyboardButton(text="⬆️ Neo Start — 199 ₽ (15 фото)", callback_data="paywall:neo_start")])
            buttons.append([InlineKeyboardButton(text="⬆️ Neo Pro — 499 ₽ (50 фото)", callback_data="paywall:neo_pro")])
            buttons.append([InlineKeyboardButton(text="⬆️ Neo Unlimited — 990 ₽ (120 фото)", callback_data="paywall:neo_unlimited")])

        if is_collection:
            status_text = (
                f"📸 Ваша коллекция\n\n"
                f"Всего превью: {takes_used * 3}/{takes_limit * 3}\n"
                f"Выберите до {hd_limit} 4K — осталось: {hd_rem}\n"
                f"В избранном: {fav_count} (отмечено для 4K: {selected_count})"
            )
        else:
            status_text = (
                f"📸 Ваш пакет\n\n"
                f"Осталось фото: {remaining} из {takes_limit}\n"
                f"В избранном: {fav_count}"
            )

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.answer(
            status_text,
            reply_markup=keyboard,
        )
        await state.set_state(BotStates.session_active)
        await callback.answer()
    except Exception:
        logger.exception("session_status error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)


@session_router.callback_query(F.data.startswith("paywall:"))
async def paywall_pack_selected(callback: CallbackQuery, bot: Bot):
    """User selected pack — show payment method screen (только ЮMoney)."""
    telegram_id = str(callback.from_user.id)
    pack_id = callback.data.split(":", 1)[1]
    callback_acknowledged = False

    async def _answer_once(text: str | None = None, **kwargs):
        nonlocal callback_acknowledged
        if callback_acknowledged:
            return
        try:
            await callback.answer(text, **kwargs)
        except TelegramBadRequest as e:
            msg = (getattr(e, "message", None) or str(e) or "").lower()
            if "query is too old" in msg or "query id is invalid" in msg:
                callback_acknowledged = True
                return
            raise
        callback_acknowledged = True

    if pack_id not in PRODUCT_LADDER_IDS:
        await _answer_once("❌ Пакет недоступен", show_alert=True)
        return
    try:
        with get_db_session() as db:
            pack = db.query(Pack).filter(Pack.id == pack_id, Pack.enabled == True).one_or_none()
            if not pack:
                await _answer_once("❌ Пакет недоступен", show_alert=True)
                return

            user_service = UserService(db)
            user = user_service.get_or_create_user(
                telegram_id,
                telegram_username=callback.from_user.username,
                telegram_first_name=callback.from_user.first_name,
                telegram_last_name=callback.from_user.last_name,
            )
            # Воронка: считаем любой выбор тарифа до проверки trial
            analytics = ProductAnalyticsService(db)
            active_session = SessionService(db).get_active_session(user.id)
            analytics.track_funnel_step(
                "pack_selected",
                user.id,
                session_id=active_session.id if active_session else None,
                pack_id=pack_id,
                source_component="bot",
                properties={"pack_id": pack_id},
            )

            # Чистый переход: удаляем экран с общим списком тарифов после выбора конкретного пакета.
            try:
                await callback.message.delete()
            except Exception:
                pass

            if pack.is_trial and user.trial_purchased:
                await _answer_once("Пробный пакет уже был использован", show_alert=True)
                return

            from app.services.balance_tariffs import DISPLAY_RUB, SHORT_NAMES
            pack_name = SHORT_NAMES.get(pack_id, pack.name)
            pack_emoji = pack.emoji
            pack_takes_limit = getattr(pack, "takes_limit", None)
            pack_hd_amount = getattr(pack, "hd_amount", None)
            rub = DISPLAY_RUB.get(pack_id) or round((pack.stars_price or 0) * getattr(settings, "star_to_rub", 1.3))

            # Три пакета (Neo Start / Neo Pro / Neo Unlimited) — сразу ссылка ЮKassa, без экрана выбора способа оплаты
            if pack_id in ("neo_start", "neo_pro", "neo_unlimited"):
                from app.services.yookassa.client import YooKassaClient
                from app.services.pack_order.service import PackOrderService
                yookassa = YooKassaClient()
                if not yookassa.is_configured():
                    await callback.message.answer(
                        "⚠️ Сейчас оплата временно недоступна.\n\n"
                        "Мы уже работаем над решением.\n\n"
                        "Нажмите «Помощь», если нужно оформить пакет вручную.",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="🛟 Помощь", callback_data="profile:support")],
                            [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
                        ]),
                    )
                    await _answer_once()
                    return
                bot_username = (getattr(settings, "telegram_bot_username", None) or "").strip()
                if not bot_username:
                    await callback.message.answer(
                        "⚠️ Сейчас оплата временно недоступна.\n\n"
                        "Мы уже работаем над решением.\n\n"
                        "Нажмите «Помощь», если нужно оформить пакет вручную.",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="🛟 Помощь", callback_data="profile:support")],
                            [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
                        ]),
                    )
                    await _answer_once()
                    return
                # Подтверждаем callback до потенциально долгого сетевого запроса в YooKassa.
                await _answer_once()
                create_lock = None
                create_lock_key = f"pack_order_create:{telegram_id}:{pack_id}"
                lock_acquired = False
                try:
                    create_lock = IdempotencyStore()
                    lock_acquired = create_lock.check_and_set(create_lock_key, ttl_seconds=20)
                except Exception as e:
                    logger.warning("pack_order_create_lock_unavailable", extra={"user_id": telegram_id, "pack_id": pack_id, "error": str(e)})
                    lock_acquired = True
                if not lock_acquired:
                    await callback.message.answer(
                        "⏳ Уже создаём ссылку на оплату. Подождите пару секунд.",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
                        ]),
                    )
                    return
                pack_order_svc = PackOrderService(db)
                try:
                    existing_pending = pack_order_svc.get_pending_order(telegram_id, pack_id)
                    if existing_pending and existing_pending.confirmation_url:
                        order = existing_pending
                        confirmation_url = existing_pending.confirmation_url
                    else:
                        order, confirmation_url = pack_order_svc.create_order(telegram_id, pack_id, bot_username)
                finally:
                    if create_lock is not None and lock_acquired:
                        try:
                            create_lock.release(create_lock_key)
                        except Exception:
                            logger.warning("pack_order_create_lock_release_failed", extra={"user_id": telegram_id, "pack_id": pack_id})
                if not order or not confirmation_url:
                    await callback.message.answer(
                        "⚠️ Возникла временная ошибка при создании платежа.\n\n"
                        "Ваш заказ не создан. Деньги не списаны.\n\n"
                        "Попробуйте снова или обратитесь в поддержку.",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data=f"paywall:{pack_id}")],
                            [InlineKeyboardButton(text="🛟 Помощь", callback_data="profile:support")],
                        ]),
                    )
                    await _answer_once()
                    return
                db.commit()
                if str(pack_id or "").strip().lower() == "neo_start":
                    msg_text = (
                        "🚀 Neo Start\n\n"
                        "После оплаты вы получите:\n\n"
                        "• 15 фото в любых трендовых образах\n"
                        "• возможность перегенерации\n"
                        "• фото без водяных знаков\n"
                        "• максимальное качество\n\n"
                        "Доступ откроется сразу после оплаты"
                    )
                else:
                    msg_text = (
                        f"{pack_emoji} *{pack_name}*\n\n"
                        "Перейдите к оплате — пакет активируется автоматически после подтверждения.\n\n"
                        "Ваш заказ сохранён."
                    )
                await callback.message.answer(
                    msg_text,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text=f"💵 Оплатить {rub} ₽", url=confirmation_url)],
                        [InlineKeyboardButton(text="♻️ Проверить оплату", callback_data=f"pack_check:{order.id}")],
                        [InlineKeyboardButton(text="🛟 Помощь", callback_data="profile:support")],
                    ]),
                )
                await _answer_once()
                return

        with get_db_session() as db:
            audit = AuditService(db)
            audit.log(
                actor_type="user",
                actor_id=telegram_id,
                action="pay_click",
                entity_type="pack",
                entity_id=pack_id,
                payload={"pack_name": pack_name, "flow": "payment_method_screen"},
            )
            user = UserService(db).get_by_telegram_id(telegram_id)
            if user:
                analytics = ProductAnalyticsService(db)
                active_session = SessionService(db).get_active_session(user.id)
                analytics.track_button_click(
                    user.id,
                    button_id=f"pack_{pack_id}",
                    session_id=active_session.id if active_session else None,
                    source_component="bot",
                    pack_id=pack_id,
                )
                analytics.track(
                    "payment_methods_shown",
                    user.id,
                    session_id=active_session.id if active_session else None,
                    pack_id=pack_id,
                    properties={"entry_point": "paywall"},
                )

        trust_text = (
            f"{pack_emoji} *{pack_name}*\n\n"
            f"Что получите: {pack_takes_limit} фото + {pack_hd_amount} 4K без водяного знака.\n"
            f"Сумма: *{rub} ₽*\n\n"
            "После оплаты пакет активируется автоматически. Выберите способ оплаты ЮMoney:"
        )
        await callback.message.answer(
            trust_text,
            parse_mode="Markdown",
            reply_markup=_payment_method_keyboard(pack_id),
        )
        await _answer_once()
    except Exception:
        logger.exception("paywall_pack_selected error", extra={"user_id": telegram_id})
        await _answer_once("❌ Ошибка", show_alert=True)


@session_router.callback_query(F.data == "pay_method:other")
async def pay_method_other(callback: CallbackQuery):
    """Подсказка по неактуальной кнопке из старых сообщений."""
    telegram_id = str(callback.from_user.id)
    try:
        with get_db_session() as db:
            user = UserService(db).get_by_telegram_id(telegram_id)
            if user:
                ProductAnalyticsService(db).track_button_click(
                    user.id,
                    button_id="pay_other",
                    source_component="bot",
                )
    except Exception:
        logger.exception("button_click track failed pay_other")
    await callback.answer(
        "Сейчас доступна только оплата через ЮMoney.",
        show_alert=True,
    )


@session_router.callback_query(
    F.data.startswith("pay_method:yoomoney:") & ~F.data.startswith("pay_method:yoomoney_link:")
)
async def pay_method_yoomoney(callback: CallbackQuery, bot: Bot):
    """Оплата через ЮMoney — sendInvoice в RUB с provider_token (нативная интеграция)."""
    telegram_id = str(callback.from_user.id)
    pack_id = callback.data.split(":")[-1]
    if pack_id not in PRODUCT_LADDER_IDS:
        await callback.answer("❌ Пакет недоступен", show_alert=True)
        return
    try:
        analytics_session_id: str | None = None
        with get_db_session() as db:
            pack = db.query(Pack).filter(Pack.id == pack_id, Pack.enabled == True).one_or_none()
            if not pack:
                await callback.answer("❌ Пакет недоступен", show_alert=True)
                return

            user_service = UserService(db)
            user = user_service.get_or_create_user(
                telegram_id,
                telegram_username=callback.from_user.username,
                telegram_first_name=callback.from_user.first_name,
                telegram_last_name=callback.from_user.last_name,
            )

            if pack.is_trial and user.trial_purchased:
                await callback.answer("Пробный пакет уже был использован", show_alert=True)
                return

            from app.services.balance_tariffs import DISPLAY_RUB, SHORT_NAMES
            pack_name = SHORT_NAMES.get(pack_id, pack.name)
            pack_emoji = pack.emoji
            pack_description = pack.description
            pack_takes_limit = getattr(pack, "takes_limit", None)
            pack_hd_amount = getattr(pack, "hd_amount", None)
            rub = DISPLAY_RUB.get(pack_id) or round((pack.stars_price or 0) * getattr(settings, "star_to_rub", 1.3))
            amount_kopecks = rub * 100

        with get_db_session() as db:
            user = UserService(db).get_by_telegram_id(telegram_id)
            if user:
                analytics = ProductAnalyticsService(db)
                active_session = SessionService(db).get_active_session(user.id)
                analytics_session_id = active_session.id if active_session else None
                analytics.track_button_click(
                    user.id,
                    button_id="pay_yoomoney",
                    session_id=active_session.id if active_session else None,
                    source_component="bot",
                    pack_id=pack_id,
                    properties={"pack_id": pack_id},
                )
                analytics.track(
                    "payment_method_selected",
                    user.id,
                    session_id=active_session.id if active_session else None,
                    pack_id=pack_id,
                    properties={"method": "yoomoney"},
                )
                analytics.track(
                    "yoomoney_checkout_created",
                    user.id,
                    session_id=active_session.id if active_session else None,
                    pack_id=pack_id,
                    properties={"amount_kopecks": amount_kopecks, "amount_rub": rub},
                )
                analytics.track_payment_event(
                    "pay_initiated",
                    user.id,
                    method="yoomoney",
                    session_id=active_session.id if active_session else None,
                    pack_id=pack_id,
                    price=float(pack.stars_price or 0),
                    price_rub=float(rub),
                    currency="RUB",
                    source_component="bot",
                    properties={"amount_kopecks": amount_kopecks, "amount_rub": rub},
                )
                pay_initiated_total.labels(pack_id=pack_id).inc()

        provider_token = getattr(settings, "telegram_payment_provider_token", "") or ""
        if not provider_token:
            await callback.answer("Оплата ЮMoney временно недоступна. Попробуйте позже или обратитесь в поддержку.", show_alert=True)
            return

        payload = (
            f"yoomoney_session:{pack_id}:{analytics_session_id}"
            if analytics_session_id
            else f"yoomoney_session:{pack_id}"
        )
        title = f"{pack_emoji} {pack_name}"
        description = pack_description or f"{pack_takes_limit} фото + {pack_hd_amount} 4K без водяного знака"
        prices = [LabeledPrice(label=f"{pack_name} — {rub} ₽", amount=amount_kopecks)]

        await bot.send_invoice(
            chat_id=callback.message.chat.id,
            title=title,
            description=description,
            payload=payload,
            provider_token=provider_token,
            currency="RUB",
            prices=prices,
        )
        await callback.answer()
    except TelegramBadRequest as e:
        if "PAYMENT_PROVIDER_INVALID" in (getattr(e, "message", None) or str(e)):
            logger.warning("pay_method_yoomoney PAYMENT_PROVIDER_INVALID", extra={"user_id": telegram_id})
            await callback.answer(
                "Оплата ЮMoney временно недоступна. Попробуйте позже или обратитесь в поддержку.",
                show_alert=True,
            )
        else:
            logger.exception("pay_method_yoomoney TelegramBadRequest", extra={"user_id": telegram_id})
            await callback.answer("❌ Ошибка оплаты ЮMoney. Попробуйте позже или обратитесь в поддержку.", show_alert=True)
    except Exception:
        logger.exception("pay_method_yoomoney error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)


@session_router.callback_query(F.data.startswith("pay_method:yoomoney_link:"))
async def pay_method_yoomoney_link(callback: CallbackQuery, bot: Bot):
    """Оплата ЮMoney по ссылке — createInvoiceLink, тот же payload и обработка pre_checkout/successful_payment."""
    telegram_id = str(callback.from_user.id)
    pack_id = callback.data.split(":")[-1]
    if pack_id not in PRODUCT_LADDER_IDS:
        await callback.answer("❌ Пакет недоступен", show_alert=True)
        return
    try:
        analytics_session_id: str | None = None
        with get_db_session() as db:
            pack = db.query(Pack).filter(Pack.id == pack_id, Pack.enabled == True).one_or_none()
            if not pack:
                await callback.answer("❌ Пакет недоступен", show_alert=True)
                return

            user_service = UserService(db)
            user = user_service.get_or_create_user(
                telegram_id,
                telegram_username=callback.from_user.username,
                telegram_first_name=callback.from_user.first_name,
                telegram_last_name=callback.from_user.last_name,
            )

            if pack.is_trial and user.trial_purchased:
                await callback.answer("Пробный пакет уже был использован", show_alert=True)
                return

            from app.services.balance_tariffs import DISPLAY_RUB, SHORT_NAMES
            pack_name = SHORT_NAMES.get(pack_id, pack.name)
            pack_emoji = pack.emoji
            pack_description = pack.description
            pack_takes_limit = getattr(pack, "takes_limit", None)
            pack_hd_amount = getattr(pack, "hd_amount", None)
            rub = DISPLAY_RUB.get(pack_id) or round((pack.stars_price or 0) * getattr(settings, "star_to_rub", 1.3))
            amount_kopecks = rub * 100

        with get_db_session() as db:
            user = UserService(db).get_by_telegram_id(telegram_id)
            if user:
                analytics = ProductAnalyticsService(db)
                active_session = SessionService(db).get_active_session(user.id)
                analytics_session_id = active_session.id if active_session else None
                analytics.track_button_click(
                    user.id,
                    button_id="pay_yoomoney_link",
                    session_id=active_session.id if active_session else None,
                    source_component="bot",
                    pack_id=pack_id,
                    properties={"pack_id": pack_id},
                )
                analytics.track(
                    "payment_method_selected",
                    user.id,
                    session_id=active_session.id if active_session else None,
                    pack_id=pack_id,
                    properties={"method": "yoomoney_link"},
                )
                analytics.track(
                    "yoomoney_checkout_created",
                    user.id,
                    session_id=active_session.id if active_session else None,
                    pack_id=pack_id,
                    properties={"amount_kopecks": amount_kopecks, "amount_rub": rub},
                )
                analytics.track_payment_event(
                    "pay_initiated",
                    user.id,
                    method="yoomoney_link",
                    session_id=active_session.id if active_session else None,
                    pack_id=pack_id,
                    price=float(pack.stars_price or 0),
                    price_rub=float(rub),
                    currency="RUB",
                    source_component="bot",
                    properties={"amount_kopecks": amount_kopecks, "amount_rub": rub},
                )

        provider_token = getattr(settings, "telegram_payment_provider_token", "") or ""
        if not provider_token:
            await callback.answer("Оплата ЮMoney временно недоступна. Попробуйте позже или обратитесь в поддержку.", show_alert=True)
            return

        payload = (
            f"yoomoney_session:{pack_id}:{analytics_session_id}"
            if analytics_session_id
            else f"yoomoney_session:{pack_id}"
        )
        title = f"{pack_emoji} {pack_name}"
        description = pack_description or f"{pack_takes_limit} фото + {pack_hd_amount} 4K без водяного знака"
        prices = [LabeledPrice(label=f"{pack_name} — {rub} ₽", amount=amount_kopecks)]

        link = await bot.create_invoice_link(
            title=title,
            description=description,
            payload=payload,
            provider_token=provider_token,
            currency="RUB",
            prices=prices,
        )
        await callback.message.answer(
            "Оплатите по ссылке (откроется окно оплаты ЮMoney):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Оплатить", url=link)],
            ]),
        )
        await callback.answer()
    except TelegramBadRequest as e:
        if "PAYMENT_PROVIDER_INVALID" in (getattr(e, "message", None) or str(e)):
            logger.warning("pay_method_yoomoney_link PAYMENT_PROVIDER_INVALID", extra={"user_id": telegram_id})
            await callback.answer(
                "Оплата ЮMoney временно недоступна. Попробуйте позже или обратитесь в поддержку.",
                show_alert=True,
            )
        else:
            logger.exception("pay_method_yoomoney_link TelegramBadRequest", extra={"user_id": telegram_id})
            await callback.answer("❌ Ошибка оплаты ЮMoney. Попробуйте позже или обратитесь в поддержку.", show_alert=True)
    except Exception:
        logger.exception("pay_method_yoomoney_link error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)


@session_router.callback_query(F.data.startswith("pay_method:stars:"))
async def pay_method_stars(callback: CallbackQuery, bot: Bot):
    """Legacy callback: Stars отключены, оставляем редирект на ЮMoney."""
    pack_id = callback.data.split(":")[-1]
    await callback.answer("Оплата через Stars отключена. Используйте ЮMoney.", show_alert=True)
    try:
        if pack_id in PRODUCT_LADDER_IDS:
            reply_markup = _payment_method_keyboard(pack_id)
        else:
            reply_markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🛒 Открыть магазин", callback_data="shop:open")],
                [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
            ])
        await callback.message.answer(
            "Доступна только оплата через ЮMoney. Выберите вариант оплаты:",
            reply_markup=reply_markup,
        )
    except Exception:
        logger.exception("pay_method_stars redirect failed")


@session_router.callback_query(F.data.startswith("upgrade:"))
async def upgrade_session(callback: CallbackQuery, bot: Bot):
    """Legacy callback: upgrade через Stars отключен."""
    new_pack_id = callback.data.split(":", 1)[1]
    await callback.answer("Stars-апгрейд отключён. Используйте оплату через ЮMoney.", show_alert=True)
    try:
        if new_pack_id in PRODUCT_LADDER_IDS:
            await callback.message.answer(
                "Для апгрейда используйте текущую оплату через ЮMoney.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💵 Оплатить через ЮMoney", callback_data=f"paywall:{new_pack_id}")],
                    [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
                ]),
            )
        else:
            await callback.message.answer(
                "Откройте магазин и выберите пакет для оплаты через ЮMoney.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🛒 Открыть магазин", callback_data="shop:open")],
                    [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
                ]),
            )
    except Exception:
        logger.exception("upgrade_session redirect failed")
