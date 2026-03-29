import logging
import os
import random
from uuid import uuid4

from aiogram import Router, F, Bot
from aiogram.types import (
    CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, FSInputFile,
)
from aiogram.fsm.context import FSMContext

from app.bot.helpers import t, tr, get_db_session, redis_client, logger
from app.bot.keyboards import main_menu_keyboard
from app.core.config import settings
from app.services.users.service import UserService
from app.services.sessions.service import SessionService
from app.services.takes.service import TakeService
from app.services.audit.service import AuditService
from app.services.product_analytics.service import ProductAnalyticsService
from app.services.trial_v2.service import TrialV2Service
from app.services.trial_bundle_order.service import TrialBundleOrderService
from app.services.unlock_order.service import UnlockOrderService, unlock_photo_display_filename, validate_can_create_unlock
from app.services.yookassa.client import YooKassaClient, YooKassaClientError
from app.services.favorites.service import FavoriteService
from app.services.payments.service import PaymentService
from app.services.idempotency import IdempotencyStore
from app.referral.service import ReferralService
from app.models.user import User
from app.models.take import Take as TakeModel
from app.utils.metrics import pay_initiated_total

trial_router = Router()


def _trial_bundle_menu_key(telegram_id: str, take_id: str) -> str:
    return f"trial:bundle_menu:{telegram_id}:{take_id}"


def _build_trial_ref_link(code: str) -> str:
    bot_username = settings.telegram_bot_username
    return f"https://t.me/{bot_username}?start=ref_{code}" if bot_username else f"ref_{code}"


async def _replace_step_message(message, text: str, reply_markup=None) -> None:
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


async def _start_single_unlock_checkout(
    *,
    message,
    telegram_id: str,
    take_id: str,
    variant: str,
) -> None:
    """Start (or reuse) single unlock checkout for one take variant."""
    yookassa = YooKassaClient()
    if not yookassa.is_configured():
        await _replace_step_message(
            message,
            "⚠️ Платёж временно недоступен. Попробуйте позже или обратитесь в поддержку.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🆘 Помощь", callback_data="profile:support")],
                [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
            ]),
        )
        return

    create_lock = None
    create_lock_key = f"unlock_order_create:{telegram_id}:{take_id}:{variant.upper()}"
    lock_acquired = False
    try:
        create_lock = IdempotencyStore()
        lock_acquired = create_lock.check_and_set(create_lock_key, ttl_seconds=20)
    except Exception:
        lock_acquired = True
    if not lock_acquired:
        await _replace_step_message(message, "⏳ Уже создаём ссылку на оплату. Подождите пару секунд.")
        return

    with get_db_session() as db:
        ok, err = validate_can_create_unlock(db, telegram_id, take_id, variant)
        if not ok:
            if create_lock is not None and lock_acquired:
                try:
                    create_lock.release(create_lock_key)
                except Exception:
                    pass
            await _replace_step_message(message, f"❌ {err}")
            return
        unlock_svc = UnlockOrderService(db)
        existing_paid = unlock_svc.get_order_with_paid_or_delivered(telegram_id, take_id, variant)
        if existing_paid:
            if create_lock is not None and lock_acquired:
                try:
                    create_lock.release(create_lock_key)
                except Exception:
                    pass
            await _replace_step_message(
                message,
                "Это фото уже оплачено. Нажмите «Получить фото снова».",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Получить фото снова", callback_data=f"unlock_resend:{existing_paid.id}")],
                    [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
                ]),
            )
            return

        order, is_new = unlock_svc.create_or_get_pending_order(telegram_id, take_id, variant)
        if not is_new and order.confirmation_url:
            if create_lock is not None and lock_acquired:
                try:
                    create_lock.release(create_lock_key)
                except Exception:
                    pass
            await _replace_step_message(
                message,
                "Перейдите по ссылке для оплаты:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔥 Выгоднее взять тариф", callback_data="shop:open:tariff_better")],
                    [InlineKeyboardButton(text="Разово оплатить через ЮMoney", url=order.confirmation_url)],
                    [InlineKeyboardButton(text="♻️ Проверить оплату", callback_data=f"unlock_check:{order.id}")],
                    [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
                ]),
            )
            return

        bot_username = (getattr(settings, "telegram_bot_username", None) or "").strip()
        if not bot_username:
            if create_lock is not None and lock_acquired:
                try:
                    create_lock.release(create_lock_key)
                except Exception:
                    pass
            await _replace_step_message(
                message,
                "⚠️ Ошибка конфигурации оплаты. Обратитесь в поддержку.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🆘 Помощь", callback_data="profile:support")],
                ]),
            )
            return
        return_url = f"https://t.me/{bot_username}?start=unlock_done_{order.id}"
        idempotence_key = str(uuid4())
        try:
            result = yookassa.create_payment(
                order_id=order.id,
                return_url=return_url,
                idempotence_key=idempotence_key,
            )
        except YooKassaClientError:
            if create_lock is not None and lock_acquired:
                try:
                    create_lock.release(create_lock_key)
                except Exception:
                    pass
            await _replace_step_message(
                message,
                "⚠️ Не удалось создать платёж. Попробуйте ещё раз.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🆘 Помощь", callback_data="profile:support")],
                ]),
            )
            return

        conf = result.get("confirmation", {}) or {}
        confirmation_url = (conf.get("confirmation_url") or "").strip()
        yookassa_payment_id = (result.get("id") or "").strip()
        if not confirmation_url or not yookassa_payment_id:
            if create_lock is not None and lock_acquired:
                try:
                    create_lock.release(create_lock_key)
                except Exception:
                    pass
            await _replace_step_message(
                message,
                "⚠️ Ошибка платёжного провайдера. Попробуйте позже.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🆘 Помощь", callback_data="profile:support")],
                ]),
            )
            return
        unlock_svc.set_payment_created(
            order.id,
            yookassa_payment_id,
            confirmation_url,
            idempotence_key,
        )
        await _replace_step_message(
            message,
            "Всего 99 ₽ — и фото сразу будет доступно в оригинальном качестве ✨\n"
            "🔒 Безопасная оплата через ЮMoney\n"
            "Банковская карта, SberPay или СБП\n\n"
            "👇 Нажмите кнопку ниже, чтобы оплатить\n\n"
            "После оплаты фото придёт автоматически.\n"
            "Если не появилось — нажмите «Проверить оплату»",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔥 Выгоднее взять тариф", callback_data="shop:open:tariff_better")],
                [InlineKeyboardButton(text="Разово оплатить через ЮMoney", url=confirmation_url)],
                [InlineKeyboardButton(text="♻️ Проверить оплату", callback_data=f"unlock_check:{order.id}")],
                [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
            ]),
        )
    if create_lock is not None and lock_acquired:
        try:
            create_lock.release(create_lock_key)
        except Exception:
            pass


@trial_router.callback_query(F.data.startswith("trial_select:"))
async def trial_select_preview(callback: CallbackQuery):
    """Trial V2: queue selected preview(s) then show payment/referral branch."""
    telegram_id = str(callback.from_user.id)
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    take_id, variant = parts[1], parts[2].upper()
    if variant not in ("A", "B", "C", "ALL"):
        await callback.answer("❌ Неверный вариант", show_alert=True)
        return

    try:
        with get_db_session() as db:
            user = UserService(db).get_or_create_user(
                telegram_id,
                telegram_username=callback.from_user.username,
                telegram_first_name=callback.from_user.first_name,
                telegram_last_name=callback.from_user.last_name,
            )
            if not bool(getattr(user, "trial_v2_eligible", False)):
                await callback.answer("Эта опция доступна только в Trial V2.", show_alert=True)
                return
            take = TakeService(db).get_take(take_id)
            if not take or str(take.user_id) != str(user.id):
                await callback.answer("❌ Нет доступа", show_alert=True)
                return
            trial_svc = TrialV2Service(db)
            variants: list[str]
            if variant == "ALL":
                variants = trial_svc.list_available_variants_for_take(take)
                if len(variants) != 3:
                    await callback.answer("Bundle доступен только когда готовы все 3 фото.", show_alert=True)
                    return
                variants = [v for v in ("A", "B", "C") if v in variants]
            else:
                _, orig = TakeService(db).get_variant_paths(take, variant)
                if not orig:
                    await callback.answer("❌ Вариант недоступен", show_alert=True)
                    return
                variants = [variant]

            for v in variants:
                trial_svc.enqueue_selection(
                    user_id=user.id,
                    take_id=take_id,
                    variant=v,
                    source="trial_select",
                )
            try:
                ProductAnalyticsService(db).track(
                    "trial_selection_queued",
                    user.id,
                    take_id=take_id,
                    session_id=take.session_id,
                    properties={"variants": variants},
                )
            except Exception:
                logger.exception("trial_selection_queued_track_failed", extra={"user_id": telegram_id, "take_id": take_id})

        await callback.answer("✅ Выбор сохранён")
        if variant == "ALL":
            text = "Вы выбрали все 3 фото. Что дальше?"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔥 Тариф выгоднее", callback_data="shop:open:tariff_better")],
                [InlineKeyboardButton(text="💵 Оплатить и открыть все 3 — 129 ₽", callback_data=f"trial_action:pay_bundle:{take_id}")],
                [InlineKeyboardButton(text="🎁 Получить бесплатно за друга", callback_data="trial_action:referral")],
                [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
            ])
        else:
            idx_map = {"A": "1", "B": "2", "C": "3"}
            selected_idx = idx_map.get(variant, variant)
            praise = random.choice([
                "Сильный выбор 💪",
                "Очень даже 👍",
                "Очень даже неплохо 👍",
                "Прям кайф 😌",
            ])
            text = (
                f"Вы выбрали фото [{selected_idx}] - {praise}\n\n"
                "Фото готово — выберите удобный способ получить его"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📥 Скачать без водяного знака", callback_data=f"trial_action:pay:{take_id}:{variant}")],
                [InlineKeyboardButton(text="🎁 Получить бесплатно, пригласив друга", callback_data="trial_action:referral")],
            ])
        sent = await callback.message.answer(text, reply_markup=kb)
        if variant == "ALL":
            try:
                redis_client.setex(
                    _trial_bundle_menu_key(telegram_id, take_id),
                    24 * 60 * 60,
                    str(sent.message_id),
                )
            except Exception:
                logger.warning("trial_bundle_menu_store_failed", extra={"user_id": telegram_id, "take_id": take_id})
    except Exception:
        logger.exception("trial_select_preview_error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)


@trial_router.callback_query(F.data.startswith("trial_action:pay:"))
async def trial_action_pay_single(callback: CallbackQuery):
    """Trial V2: single photo unlock payment."""
    telegram_id = str(callback.from_user.id)
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    take_id, variant = parts[2], parts[3].upper()
    await callback.answer()
    await _start_single_unlock_checkout(
        message=callback.message,
        telegram_id=telegram_id,
        take_id=take_id,
        variant=variant,
    )


@trial_router.callback_query(F.data.startswith("trial_action:pay_bundle:"))
async def trial_action_pay_bundle(callback: CallbackQuery):
    """Trial V2: bundle unlock payment for all 3 variants (129 ₽)."""
    telegram_id = str(callback.from_user.id)
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    take_id = parts[2]
    try:
        with get_db_session() as db:
            user = UserService(db).get_or_create_user(
                telegram_id,
                telegram_username=callback.from_user.username,
                telegram_first_name=callback.from_user.first_name,
                telegram_last_name=callback.from_user.last_name,
            )
            if not bool(getattr(user, "trial_v2_eligible", False)):
                await callback.answer("Эта опция доступна только в Trial V2.", show_alert=True)
                return
            take = TakeService(db).get_take(take_id)
            if not take or str(take.user_id) != str(user.id):
                await callback.answer("❌ Нет доступа", show_alert=True)
                return
            if len(TrialV2Service(db).list_available_variants_for_take(take)) != 3:
                await callback.answer("Bundle доступен только когда готовы все 3 фото.", show_alert=True)
                return
            svc = TrialBundleOrderService(db)
            done = svc.get_paid_or_delivered(telegram_id, take_id)
            if done:
                await callback.message.answer(
                    "Этот набор уже оплачен. Нажмите «Проверить оплату», если файлы ещё не пришли.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="♻️ Проверить оплату", callback_data=f"trial_bundle_check:{done.id}")],
                        [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
                    ]),
                )
                await callback.answer()
                return
            order, confirmation_url = svc.create_or_get_order(
                telegram_user_id=telegram_id,
                take_id=take_id,
            )
            if not order or not confirmation_url:
                await callback.answer("❌ Не удалось создать платёж", show_alert=True)
                return
            try:
                ProductAnalyticsService(db).track(
                    "trial_bundle_pay_initiated",
                    user.id,
                    take_id=take_id,
                    session_id=take.session_id,
                    properties={"order_id": order.id, "amount_kopecks": order.amount_kopecks},
                )
            except Exception:
                logger.exception("trial_bundle_pay_initiated_track_failed", extra={"user_id": telegram_id, "take_id": take_id})
        await callback.message.answer(
            "Оплатите bundle 129 ₽ — после оплаты отправим все 3 фото в полном качестве.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔥 Тариф выгоднее", callback_data="shop:open:tariff_better")],
                [InlineKeyboardButton(text="💵 Оплатить через ЮMoney", url=confirmation_url)],
                [InlineKeyboardButton(text="♻️ Проверить оплату", callback_data=f"trial_bundle_check:{order.id}")],
                [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
            ]),
        )
        await callback.answer()
    except Exception:
        logger.exception("trial_action_pay_bundle_error", extra={"user_id": telegram_id, "take_id": take_id})
        await callback.answer("❌ Ошибка", show_alert=True)


@trial_router.callback_query(F.data.startswith("trial_bundle_check:"))
async def trial_bundle_check_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)
    order_id = (callback.data or "").split(":", 1)[1].strip()
    if not order_id:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    lock_key = f"trial_bundle_check:{telegram_id}:{order_id}"
    lock_store = None
    lock_reserved = False
    try:
        try:
            lock_store = IdempotencyStore()
            lock_reserved = lock_store.check_and_set(lock_key, ttl_seconds=20)
            if not lock_reserved:
                await callback.answer("⏳ Проверка уже выполняется…")
                return
        except Exception:
            pass
        with get_db_session() as db:
            svc = TrialBundleOrderService(db)
            order = svc.get_by_id(order_id)
            if not order or str(order.telegram_user_id) != telegram_id:
                await callback.answer("Заказ не найден.", show_alert=True)
                return
            if order.status == "delivered":
                await callback.answer("Файлы уже отправлены.")
                return
            if order.status == "delivery_failed":
                from app.core.celery_app import celery_app as _celery
                _celery.send_task(
                    "app.workers.tasks.deliver_trial_bundle.deliver_trial_bundle",
                    args=[order.id],
                )
                await callback.answer("Повторяем отправку файлов…")
                return
            if order.status == "paid":
                from app.core.celery_app import celery_app as _celery
                _celery.send_task(
                    "app.workers.tasks.deliver_trial_bundle.deliver_trial_bundle",
                    args=[order.id],
                )
                await callback.answer("Оплата подтверждена. Отправляем файлы…")
                return
            if order.status not in ("payment_pending", "created") or not order.yookassa_payment_id:
                await callback.answer("Платёж не найден.", show_alert=True)
                return
            yookassa = YooKassaClient()
            payment = yookassa.get_payment(order.yookassa_payment_id) if yookassa.is_configured() else None
            payment_status = (payment or {}).get("status")
            if payment_status in ("canceled", "failed"):
                svc.mark_canceled(order_id=order.id)
                await callback.answer("Платёж отменён.", show_alert=True)
                return
            if payment_status != "succeeded":
                await callback.answer("Пока не подтверждено. Попробуйте чуть позже.")
                return

            svc.mark_paid(order_id=order.id)
            PaymentService(db).record_yookassa_trial_bundle_payment(order)
            from app.core.celery_app import celery_app as _celery
            _celery.send_task(
                "app.workers.tasks.deliver_trial_bundle.deliver_trial_bundle",
                args=[order.id],
            )
            user = UserService(db).get_by_telegram_id(telegram_id)
            if user:
                try:
                    ProductAnalyticsService(db).track(
                        "trial_bundle_pay_success",
                        user.id,
                        take_id=order.take_id,
                        properties={"order_id": order.id},
                    )
                except Exception:
                    logger.exception("trial_bundle_pay_success_track_failed", extra={"user_id": telegram_id, "order_id": order.id})
            await callback.answer("Оплата подтверждена. Отправляем все 3 фото…")
    except Exception:
        logger.exception("trial_bundle_check_callback_error", extra={"user_id": telegram_id, "order_id": order_id})
        await callback.answer("❌ Ошибка", show_alert=True)
    finally:
        if lock_store is not None and lock_reserved:
            try:
                lock_store.release(lock_key)
            except Exception:
                pass


@trial_router.callback_query(F.data == "trial_action:referral")
async def trial_action_referral(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)
    try:
        with get_db_session() as db:
            user = UserService(db).get_or_create_user(
                telegram_id,
                telegram_username=callback.from_user.username,
                telegram_first_name=callback.from_user.first_name,
                telegram_last_name=callback.from_user.last_name,
            )
            code = ReferralService(db).get_or_create_code(user)
        link = _build_trial_ref_link(code)
        await callback.message.answer(
            "Пригласите друга и получите 1 фото в полном качестве бесплатно, без водяных знаков\n\n"
            "Как это работает:\n\n"
            "1. Нажмите «Получить ссылку», чтобы получить свою персональную ссылку.\n"
            "2. Отправьте её другу.\n"
            "3. Друг перейдёт по ссылке, зайдёт в бота и сделает первую генерацию любого тренда.\n"
            "4. После этого вы автоматически получите 1 фото в полном качестве без водяных знаков.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔗 Получить ссылку", callback_data="trial_ref:get_link")],
                [InlineKeyboardButton(text="💬 Отправить другу", switch_inline_query=f"Попробуй бота: {link}")],
                [InlineKeyboardButton(text="🏠 В меню", callback_data="nav:menu")],
            ]),
        )
        await callback.answer()
    except Exception:
        logger.exception("trial_action_referral_error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)


@trial_router.callback_query(F.data == "trial_ref:get_link")
async def trial_ref_get_link(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)
    try:
        with get_db_session() as db:
            user = UserService(db).get_or_create_user(
                telegram_id,
                telegram_username=callback.from_user.username,
                telegram_first_name=callback.from_user.first_name,
                telegram_last_name=callback.from_user.last_name,
            )
            code = ReferralService(db).get_or_create_code(user)
            link = _build_trial_ref_link(code)
        text = (
            "Пригласите друга и получите 1 фото в полном качестве бесплатно, без водяных знаков.\n\n"
            "Ваша персональная ссылка:\n"
            f"{link}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Отправить другу", switch_inline_query=f"Попробуй бота: {link}")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="nav:menu")],
        ])
        await callback.message.answer(text, reply_markup=kb)
        await callback.answer("Ссылка готова")
    except Exception:
        logger.exception("trial_ref_get_link_error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)


@trial_router.callback_query(F.data == "trial_ref:status")
async def trial_ref_status(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)
    try:
        with get_db_session() as db:
            user = UserService(db).get_by_telegram_id(telegram_id)
            if not user:
                await callback.answer("Пользователь не найден", show_alert=True)
                return
            stats = TrialV2Service(db).get_referral_unlock_stats(user.id)
        text = (
            "📊 Статус referral unlock\n\n"
            f"Доступно наград: {stats['reward_available']}\n"
            f"В резерве: {stats['reward_reserved']}\n"
            f"Начислено всего: {stats['reward_earned_total']}/10\n"
            f"Забрано: {stats['reward_claimed_total']}\n"
            f"В очереди выбранных фото: {stats['pending_selections']}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Забрать фото", callback_data="trial_claim:next")],
            [InlineKeyboardButton(text="◀️ В профиль", callback_data="referral:back_profile")],
        ])
        await callback.message.answer(text, reply_markup=kb)
        await callback.answer()
    except Exception:
        logger.exception("trial_ref_status_error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)


@trial_router.callback_query(F.data == "trial_claim:next")
async def trial_claim_next(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)
    selection_id: str | None = None
    take_id: str | None = None
    session_id: str | None = None
    variant: str | None = None
    original_path: str | None = None
    user_id: str | None = None
    try:
        with get_db_session() as db:
            user = UserService(db).get_by_telegram_id(telegram_id)
            if not user:
                await callback.answer("Пользователь не найден", show_alert=True)
                return
            if not bool(getattr(user, "trial_v2_eligible", False)):
                await callback.answer("Эта опция доступна только в Trial V2.", show_alert=True)
                return
            user_id = user.id
            trial_svc = TrialV2Service(db)
            status, selection = trial_svc.reserve_next_reward_selection(user.id)
            if status == "no_reward":
                await callback.answer("Пока нет доступных наград.", show_alert=True)
                return
            if status == "no_selection" or not selection:
                await callback.message.answer(
                    "Награда сохранена. Выберите фото 1/2/3 после генерации — и сможете забрать его в 1 клик."
                )
                await callback.answer()
                return

            selection_id = selection.id
            take = TakeService(db).get_take(selection.take_id)
            if not take:
                trial_svc.cancel_reserved_claim(user_id=user.id, selection_id=selection.id)
                await callback.answer("Не удалось найти выбранное фото.", show_alert=True)
                return
            _, original_path = TakeService(db).get_variant_paths(take, selection.variant)
            if not original_path or not os.path.exists(original_path):
                trial_svc.cancel_reserved_claim(user_id=user.id, selection_id=selection.id)
                await callback.answer("Файл временно недоступен. Попробуйте позже.", show_alert=True)
                return
            take_id = selection.take_id
            session_id = take.session_id
            variant = selection.variant

        try:
            await callback.message.answer_document(
                FSInputFile(original_path),
                caption="✨ Готово! Мы уже отправили вам фото в полном качестве.\n\nСпасибо, что делитесь ботом с друзьями 💙",
            )
        except Exception:
            if selection_id and user_id:
                try:
                    with get_db_session() as db:
                        TrialV2Service(db).cancel_reserved_claim(user_id=user_id, selection_id=selection_id)
                except Exception:
                    logger.exception("trial_claim_cancel_after_send_fail_error", extra={"user_id": telegram_id})
            await callback.answer("Не удалось отправить файл. Награда сохранена, попробуйте ещё раз.", show_alert=True)
            return

        if selection_id and user_id:
            with get_db_session() as db:
                finalized = TrialV2Service(db).finalize_reserved_claim(
                    user_id=user_id,
                    selection_id=selection_id,
                )
                if not finalized:
                    logger.warning("trial_claim_finalize_missed", extra={"user_id": telegram_id, "selection_id": selection_id})
                else:
                    try:
                        ProductAnalyticsService(db).track(
                            "trial_referral_reward_claimed",
                            user_id,
                            take_id=take_id,
                            session_id=session_id,
                            properties={"variant": variant, "selection_id": selection_id},
                        )
                    except Exception:
                        logger.exception("trial_referral_reward_claimed_track_failed", extra={"user_id": telegram_id})
        await callback.answer("✅ Фото отправлено")
    except Exception:
        logger.exception("trial_claim_next_error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)
