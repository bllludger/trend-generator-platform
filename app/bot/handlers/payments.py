import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    FSInputFile, PreCheckoutQuery, LabeledPrice,
)
from aiogram.fsm.context import FSMContext
from sqlalchemy.orm import Session

from app.bot.states import BotStates
from app.bot.helpers import t, tr, get_db_session, _escape_markdown, logger
from app.bot.keyboards import main_menu_keyboard
from app.bot.constants import MONEY_IMAGE_PATH
from app.core.config import settings
from app.services.users.service import UserService
from app.services.sessions.service import SessionService
from app.services.payments.service import PaymentService, PRODUCT_LADDER_IDS
from app.services.takes.service import TakeService
from app.services.audit.service import AuditService
from app.services.product_analytics.service import ProductAnalyticsService
from app.services.hd_balance.service import HDBalanceService
from app.services.favorites.service import FavoriteService
from app.services.trial_v2.service import TrialV2Service
from app.services.unlock_order.service import UnlockOrderService, unlock_photo_display_filename, validate_can_create_unlock
from app.services.trial_bundle_order.service import TrialBundleOrderService
from app.services.yookassa.client import YooKassaClient, YooKassaClientError
from app.services.compensations.service import CompensationService
from app.services.balance_tariffs import build_balance_tariffs_message, get_balance_line, _pack_outcome_label
from app.models.user import User
from app.models.pack import Pack
from app.models.session import Session as SessionModel
from app.models.take import Take as TakeModel
from app.models.job import Job
from app.paywall import record_unlock as paywall_record_unlock
from app.referral.service import ReferralService
from app.utils.metrics import (
    pay_initiated_total, pay_success_total, pay_pre_checkout_rejected_total,
    payment_amount_stars_total, paywall_viewed_total,
    balance_rejected_total,
)
from app.utils.currency import format_stars_rub
from app.utils.telegram_photo import path_for_telegram_photo

payments_router = Router()


@payments_router.message(lambda m: (m.text or "").strip() == t("menu.btn.shop", "🛒 Купить пакет"))
async def shop_menu_text(message: Message):
    """Открыть магазин по нажатию кнопки в меню."""
    telegram_id = str(message.from_user.id) if message.from_user else None
    if telegram_id:
        try:
            with get_db_session() as db:
                user = UserService(db).get_or_create_user(
                    telegram_id,
                    telegram_username=message.from_user.username,
                    telegram_first_name=message.from_user.first_name,
                    telegram_last_name=message.from_user.last_name,
                )
                ProductAnalyticsService(db).track("button_click", user.id, properties={"button_id": "menu_shop"})
        except Exception:
            logger.exception("button_click track failed menu_shop")
    await _show_shop(message)


@payments_router.callback_query(F.data == "shop:open")
async def shop_menu_callback(callback: CallbackQuery):
    """Открыть магазин по нажатию инлайн-кнопки."""
    telegram_id = str(callback.from_user.id) if callback.from_user else None
    if telegram_id:
        try:
            with get_db_session() as db:
                user = UserService(db).get_by_telegram_id(telegram_id)
                if user:
                    ProductAnalyticsService(db).track("button_click", user.id, properties={"button_id": "shop_open"})
        except Exception:
            logger.exception("button_click track failed shop_open")
    await _show_shop(callback.message, edit=False)
    await callback.answer()


@payments_router.callback_query(F.data == "shop:open:tariff_better")
async def shop_menu_tariff_better_callback(callback: CallbackQuery):
    """Открыть тарифы из paywall и очистить предыдущий баннер оплаты."""
    telegram_id = str(callback.from_user.id) if callback.from_user else None
    if telegram_id:
        try:
            with get_db_session() as db:
                user = UserService(db).get_by_telegram_id(telegram_id)
                if user:
                    ProductAnalyticsService(db).track("button_click", user.id, properties={"button_id": "shop_open_tariff_better"})
        except Exception:
            logger.exception("button_click track failed shop_open_tariff_better")
    # Удаляем текущий paywall-баннер перед открытием магазина, чтобы не копить шаги в чате.
    try:
        await callback.message.delete()
    except Exception:
        pass
    await _show_shop(callback.message, edit=False)
    await callback.answer()


@payments_router.callback_query(F.data == "shop:how_buy_stars")
async def shop_how_buy_stars(callback: CallbackQuery):
    """Совместимость со старой кнопкой: показываем актуальный путь оплаты через ЮMoney."""
    telegram_id = str(callback.from_user.id) if callback.from_user else None
    if telegram_id:
        try:
            with get_db_session() as db:
                user = UserService(db).get_by_telegram_id(telegram_id)
                if user:
                    ProductAnalyticsService(db).track("button_click", user.id, properties={"button_id": "shop_how_buy_stars"})
        except Exception:
            logger.exception("button_click track failed shop_how_buy_stars")
    try:
        text = t(
            "shop.how_buy_stars",
            "📘 *Как оплатить через ЮMoney*\n\n"
            "1. Откройте магазин и выберите пакет.\n"
            "2. Нажмите оплату через ЮMoney.\n"
            "3. Подтвердите оплату в Telegram.\n\n"
            "После успешной оплаты пакет активируется автоматически.",
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Открыть магазин", callback_data="shop:open")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="nav:profile")],
        ])
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)
        await callback.answer()
    except Exception:
        logger.exception("Error in shop_how_buy_stars")
        await callback.answer(t("errors.try_later", "Произошла ошибка. Попробуйте позже."), show_alert=True)


async def _show_shop(message: Message, edit: bool = False):
    """Экран магазина — баланс + пакеты (Neo Start → Neo Pro → Neo Unlimited → Пробный). Outcome-first."""
    try:
        telegram_id = str(message.from_user.id) if message.from_user else ""
        with get_db_session() as db:
            payment_service = PaymentService(db)
            payment_service.seed_default_packs()
            db.commit()
            text, kb_dict = build_balance_tariffs_message(db, telegram_id)

        if kb_dict is None:
            await message.answer(t("shop.unavailable", "Пакеты временно недоступны."), reply_markup=main_menu_keyboard())
            return

        rows = kb_dict.get("inline_keyboard", [])
        keyboard = [
            [InlineKeyboardButton(text=btn["text"], callback_data=btn["callback_data"]) for btn in row]
            for row in rows
        ]
        kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
        if os.path.exists(MONEY_IMAGE_PATH):
            try:
                photo_path, is_temp = path_for_telegram_photo(MONEY_IMAGE_PATH)
                await message.answer_photo(
                    photo=FSInputFile(photo_path),
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=kb,
                )
                if is_temp and os.path.isfile(photo_path):
                    try:
                        os.unlink(photo_path)
                    except OSError:
                        pass
            except Exception as e:
                logger.warning("shop_money_photo_failed", extra={"path": MONEY_IMAGE_PATH, "error": str(e)})
                await message.answer(text, parse_mode="HTML", reply_markup=kb)
        else:
            await message.answer(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        logger.exception("Error in shop_menu")
        await message.answer(t("shop.load_error", "Ошибка загрузки."), reply_markup=main_menu_keyboard())


@payments_router.callback_query(F.data.startswith("buy:"))
async def buy_pack(callback: CallbackQuery, bot: Bot):
    """Пользователь открыл старую кнопку Stars — переводим в текущий flow ЮMoney."""
    await callback.answer("Оплата через Stars отключена. Используйте ЮMoney.", show_alert=True)
    try:
        await callback.message.answer(
            "Откройте магазин и выберите пакет для оплаты через ЮMoney.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🛒 Открыть магазин", callback_data="shop:open")],
                [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
            ]),
        )
    except Exception:
        logger.exception("Error in buy_pack redirect")


# ===========================================
# Разблокировка фото (unlock) — за токены или за Stars
# ===========================================

@payments_router.callback_query(F.data.startswith("unlock_tokens:"))
async def unlock_photo_with_tokens(callback: CallbackQuery, bot: Bot):
    """Разблокировать фото с водяным знаком за фото с баланса (без Stars)."""
    job_id = callback.data.split(":", 1)[1]
    telegram_id = str(callback.from_user.id)

    try:
        with get_db_session() as db:
            user_service = UserService(db)
            payment_service = PaymentService(db)
            audit = AuditService(db)
            user = user_service.get_by_telegram_id(telegram_id)
            if not user:
                await callback.answer(t("pay.user_not_found", "Пользователь не найден."), show_alert=True)
                return

            # Owner check: только владелец job может разблокировать
            job = db.query(Job).filter(Job.job_id == job_id, Job.user_id == user.id).one_or_none()
            if not job:
                await callback.answer(t("pay.photo_not_found", "Фото не найдено."), show_alert=True)
                return

            if not job.is_preview or not job.output_path_original:
                await callback.answer(t("pay.already_full", "Это фото уже в полном качестве."), show_alert=True)
                return

            preview_created_at = job.updated_at

            # Списываем токены из баланса
            unlock_cost = settings.unlock_cost_tokens
            if not user_service.debit_tokens_for_unlock(user, job_id, unlock_cost):
                await callback.answer("Недостаточно доступа. Купите пакет.", show_alert=True)
                return

            # Записать в payments для единой аналитики (pack_id=unlock_tokens)
            payment_service.record_unlock_tokens(user.id, job_id, unlock_cost)

            # Отправить оригинал без водяного знака; обновить job (источник истины оплаты)
            original_path = job.output_path_original
            job.is_preview = False
            job.unlocked_at = datetime.now(timezone.utc)
            job.unlock_method = "tokens"
            db.add(job)

            audit.log(
                actor_type="user",
                actor_id=telegram_id,
                action="unlock_with_tokens",
                entity_type="job",
                entity_id=job_id,
                payload={"tokens_spent": unlock_cost},
            )
            user_id_for_audit = user.id

        # Отправляем оригинал (вне сессии БД); аудит unlock только по факту успешной отправки
        if original_path and os.path.isfile(original_path):
            photo = FSInputFile(original_path)
            await callback.message.answer_document(
                document=photo,
                caption=t("success.unlock_caption", "🔓 Фото разблокировано! Вот ваше фото в полном качестве (без сжатия)."),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text=t("success.btn.menu", "📋 В меню"), callback_data="success_action:menu"),
                        InlineKeyboardButton(text=t("success.btn.more", "🔄 Сделать ещё"), callback_data="success_action:more"),
                    ]
                ]),
            )
            await callback.answer("Разблокировано!")
            latency = (datetime.now(timezone.utc) - preview_created_at).total_seconds() if preview_created_at else None
            paywall_record_unlock(
                job_id=job_id,
                user_id=user_id_for_audit,
                method="tokens",
                price_stars=0,
                price_tokens=unlock_cost,
                pack_id="unlock_tokens",
                receipt_id=None,
                preview_to_pay_latency_seconds=latency,
            )
        else:
            await callback.answer(f"Файл не найден. Обратитесь в поддержку: @{settings.support_username}.", show_alert=True)
        logger.info("unlock_with_tokens", extra={"user_id": telegram_id, "job_id": job_id})
    except Exception:
        logger.exception("Error in unlock_photo_with_tokens")
        await callback.answer(t("errors.try_later_short", "Ошибка. Попробуйте позже."), show_alert=True)


@payments_router.callback_query(F.data.startswith("unlock_hd:"))
async def unlock_photo_with_hd_credits(callback: CallbackQuery, bot: Bot):
    """Unlock photo using 4K credits from referral bonuses."""
    job_id = callback.data.split(":", 1)[1]
    telegram_id = str(callback.from_user.id)

    try:
        with get_db_session() as db:
            user_service = UserService(db)
            audit = AuditService(db)
            user = user_service.get_by_telegram_id(telegram_id)
            if not user:
                await callback.answer("Пользователь не найден.", show_alert=True)
                return

            job = db.query(Job).filter(Job.job_id == job_id, Job.user_id == user.id).one_or_none()
            if not job:
                await callback.answer("Фото не найдено.", show_alert=True)
                return

            if not job.is_preview or not job.output_path_original:
                await callback.answer("Это фото уже в полном качестве.", show_alert=True)
                return

            preview_created_at = job.updated_at

            ref_svc = ReferralService(db)
            if not ref_svc.spend_credits(user, 1):
                balance_rejected_total.inc()
                await callback.answer("Недостаточно бонусов 4K или есть долг.", show_alert=True)
                return

            ref_svc.mark_oldest_available_spent(user.id, 1)

            original_path = job.output_path_original
            job.is_preview = False
            job.unlocked_at = datetime.now(timezone.utc)
            job.unlock_method = "hd_credits"
            db.add(job)

            audit.log(
                actor_type="user",
                actor_id=telegram_id,
                action="referral_bonus_spent",
                entity_type="job",
                entity_id=job_id,
                payload={"hd_credits_spent": 1},
            )
            user_id_for_audit = user.id

        if original_path and os.path.isfile(original_path):
            photo = FSInputFile(original_path)
            await callback.message.answer_document(
                document=photo,
                caption="🎁 Фото разблокировано за бонус 4K! Вот ваше фото в полном качестве.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text=t("success.btn.menu", "📋 В меню"), callback_data="success_action:menu"),
                        InlineKeyboardButton(text=t("success.btn.more", "🔄 Сделать ещё"), callback_data="success_action:more"),
                    ]
                ]),
            )
            await callback.answer("Разблокировано за бонус 4K!")
            latency = (datetime.now(timezone.utc) - preview_created_at).total_seconds() if preview_created_at else None
            paywall_record_unlock(
                job_id=job_id,
                user_id=user_id_for_audit,
                method="tokens",
                price_stars=0,
                price_tokens=0,
                pack_id="hd_credit",
                receipt_id=None,
                preview_to_pay_latency_seconds=latency,
            )
        else:
            await callback.answer(f"Файл не найден. Обратитесь в поддержку: @{settings.support_username}.", show_alert=True)
        logger.info("unlock_with_hd_credits", extra={"user_id": telegram_id, "job_id": job_id})
    except Exception:
        logger.exception("Error in unlock_photo_with_hd_credits")
        await callback.answer("Ошибка. Попробуйте позже.", show_alert=True)


@payments_router.callback_query(F.data.startswith("unlock:"))
async def unlock_photo(callback: CallbackQuery, bot: Bot):
    """Разблокировать фото с водяным знаком — отправить invoice на unlock_cost_stars."""
    job_id = callback.data.split(":", 1)[1]
    telegram_id = str(callback.from_user.id)

    try:
        with get_db_session() as db:
            user_service = UserService(db)
            payment_service = PaymentService(db)
            user = user_service.get_by_telegram_id(telegram_id)
            if not user:
                await callback.answer(t("pay.user_not_found", "Пользователь не найден."), show_alert=True)
                return

            job = db.query(Job).filter(Job.job_id == job_id, Job.user_id == user.id).one_or_none()
            if not job:
                await callback.answer(t("pay.photo_not_found", "Фото не найдено."), show_alert=True)
                return

            if not job.is_preview or not job.output_path_original:
                await callback.answer(t("pay.already_full", "Это фото уже в полном качестве."), show_alert=True)
                return

            if payment_service.has_unlock_payment_for_job(job_id):
                await callback.answer(
                    t("pay.unlock_already_paid", f"Это фото уже оплачено. Если не получили файл — напишите в поддержку: @{settings.support_username}."),
                    show_alert=True,
                )
                return

            active_session = SessionService(db).get_active_session(user.id)
            payload = payment_service.build_payload(
                "unlock",
                user.id,
                job_id=job_id,
                session_id=active_session.id if active_session else None,
            )

        cost = settings.unlock_cost_stars
        rate = getattr(settings, "star_to_rub", 1.3)
        cost_str = format_stars_rub(cost, rate)

        with get_db_session() as db:
            user = UserService(db).get_by_telegram_id(telegram_id)
            if user:
                active_session = SessionService(db).get_active_session(user.id)
                ProductAnalyticsService(db).track_payment_event(
                    "pay_initiated",
                    user.id,
                    method="stars",
                    session_id=active_session.id if active_session else None,
                    pack_id="unlock",
                    price=float(cost or 0),
                    price_rub=round(cost * rate, 2),
                    currency="XTR",
                    source_component="bot",
                    properties={"job_id": job_id, "flow": "unlock"},
                )
                pay_initiated_total.labels(pack_id="unlock").inc()

        await bot.send_invoice(
            chat_id=callback.message.chat.id,
            title=t("unlock.invoice_title", "🔓 Разблокировать фото"),
            description=tr("unlock.invoice_description", "Получить фото без водяного знака в полном качестве ({cost})", cost=cost_str),
            payload=payload,
            currency="XTR",
            prices=[LabeledPrice(label=t("unlock.invoice_label", "Разблокировка"), amount=cost)],
        )
        await callback.answer()
    except Exception:
        logger.exception("Error in unlock_photo")
        await callback.answer(t("errors.try_later_short", "Ошибка. Попробуйте позже."), show_alert=True)


# ===========================================
# Telegram Payments: pre_checkout & successful_payment
# ===========================================

@payments_router.pre_checkout_query()
async def handle_pre_checkout(pre_checkout: PreCheckoutQuery, bot: Bot):
    """Валидация платежа перед списанием (Stars или ЮMoney)."""
    telegram_id = str(pre_checkout.from_user.id)
    payload = pre_checkout.invoice_payload
    total_amount = getattr(pre_checkout, "total_amount", None)
    currency = getattr(pre_checkout, "currency", None)

    try:
        with get_db_session() as db:
            payment_service = PaymentService(db)
            ok, error_msg = payment_service.validate_pre_checkout(
                payload, telegram_id, total_amount=total_amount, currency=currency
            )

        if ok:
            await bot.answer_pre_checkout_query(pre_checkout.id, ok=True)
            logger.info(
                "pre_checkout_approved",
                extra={"user": telegram_id, "payload": payload, "total_amount": total_amount},
            )
        else:
            await bot.answer_pre_checkout_query(
                pre_checkout.id, ok=False, error_message=error_msg
            )
            _reason = "other"
            if error_msg:
                em = error_msg.lower()
                if "позже" in em or "rate" in em or "много" in em:
                    _reason = "rate_limit"
                elif "сумм" in em or "amount" in em or "неверн" in em:
                    _reason = "wrong_amount"
                elif "не найден" in em or "not found" in em:
                    _reason = "user_not_found"
                elif "недоступен" in em or "unavailable" in em:
                    _reason = "pack_unavailable"
                elif "блокирован" in em or "blocked" in em:
                    _reason = "blocked"
                elif "уже использован" in em or "trial" in em:
                    _reason = "trial_used"
            pay_pre_checkout_rejected_total.labels(reason=_reason).inc()
            logger.warning(
                "pre_checkout_rejected",
                extra={
                    "user": telegram_id,
                    "payload": payload,
                    "reason": error_msg,
                    "total_amount": total_amount,
                },
            )
            payment_method = "yoomoney" if payload.startswith("yoomoney_session:") else "stars"
            with get_db_session() as db:
                user = UserService(db).get_by_telegram_id(telegram_id)
                if user:
                    ProductAnalyticsService(db).track(
                        "pay_failed",
                        user.id,
                        properties={"reason": error_msg or "rejected", "payment_method": payment_method},
                    )
    except Exception:
        logger.exception("Error in pre_checkout")
        pay_pre_checkout_rejected_total.labels(reason="internal_error").inc()
        await bot.answer_pre_checkout_query(
            pre_checkout.id, ok=False, error_message="Внутренняя ошибка. Попробуйте позже."
        )
        payment_method = "yoomoney" if payload.startswith("yoomoney_session:") else "stars"
        with get_db_session() as db:
            user = UserService(db).get_by_telegram_id(telegram_id)
            if user:
                ProductAnalyticsService(db).track(
                    "pay_failed",
                    user.id,
                    properties={"reason": "internal_error", "payment_method": payment_method},
                )


@payments_router.message(F.successful_payment)
async def handle_successful_payment(message: Message, state: FSMContext, bot: Bot):
    """Обработка успешного платежа — начисление токенов (Stars или ЮMoney)."""
    from app.bot.handlers.results import _send_pack_activated_post

    payment_info = message.successful_payment
    telegram_id = str(message.from_user.id)
    payload = payment_info.invoice_payload
    charge_id = payment_info.telegram_payment_charge_id
    provider_charge_id = payment_info.provider_payment_charge_id
    payment_committed = True  # по умолчанию не рефандим; в legacy-ветке сбрасываем в False и ставим True в finally

    try:
        # Handle session-based payloads first (Stars session/upgrade and YooMoney session)
        if payload.startswith("session:") or payload.startswith("upgrade:") or payload.startswith("yoomoney_session:"):
            with get_db_session() as db:
                payment_service = PaymentService(db)
                audit = AuditService(db)

                if payload.startswith("session:"):
                    parts = payload.split(":")
                    if len(parts) < 2:
                        await message.answer(f"⚠️ Ошибка обработки. Обратитесь в поддержку: @{settings.support_username}.")
                        return
                    pack_id = parts[1]
                    analytics_session_id = parts[2] if len(parts) > 2 else None
                    payment_obj, session, trial_flag, attached_free_takes = payment_service.process_session_purchase(
                        telegram_user_id=telegram_id,
                        telegram_payment_charge_id=charge_id,
                        provider_payment_charge_id=provider_charge_id,
                        pack_id=pack_id,
                        stars_amount=payment_info.total_amount,
                        payload=payload,
                    )
                    if trial_flag == "trial_already_used":
                        try:
                            await bot.refund_star_payment(
                                user_id=message.from_user.id,
                                telegram_payment_charge_id=charge_id,
                            )
                        except Exception:
                            logger.exception("trial_refund_failed", extra={"charge_id": charge_id})
                        await message.answer(
                            t("payment.trial_refunded", "Пробный пакет уже был использован. Средства возвращены на ваш счёт Stars."),
                            reply_markup=main_menu_keyboard(),
                        )
                        return
                    if payment_obj and session:
                        pack = payment_service.get_pack(pack_id)
                        hd_svc = HDBalanceService(db)
                        user = db.query(User).filter(User.telegram_id == telegram_id).one_or_none()
                        balance = hd_svc.get_balance(user) if user else {"total": 0}
                        is_collection = getattr(pack, "pack_subtype", "standalone") == "collection" and pack.playlist

                        if user:
                            ProductAnalyticsService(db).track_payment_event(
                                "pay_success",
                                user.id,
                                method="stars",
                                session_id=analytics_session_id or session.id,
                                pack_id=pack_id,
                                price=float(payment_info.total_amount or 0),
                                price_rub=round((payment_info.total_amount or 0) * getattr(settings, "star_to_rub", 1.3), 2),
                                currency="XTR",
                                source_component="bot",
                                properties={
                                    "charge_id": charge_id,
                                    "provider_charge_id": provider_charge_id,
                                },
                            )
                        pay_success_total.labels(pack_id=pack_id, payment_method="stars").inc()
                        payment_amount_stars_total.labels(pack_id=pack_id).inc(payment_info.total_amount)

                        remaining_display = session.takes_limit if (attached_free_takes and attached_free_takes > 0) else (session.takes_limit - session.takes_used)
                        if is_collection:
                            await state.set_state(BotStates.waiting_for_photo)
                            await message.answer(
                                f"✅ Коллекция {pack.emoji} {pack.name} активирована!\n\n"
                                f"Отправьте одно фото — по нему будут созданы все фото коллекции.",
                                reply_markup=main_menu_keyboard(),
                            )
                        else:
                            try:
                                await _send_pack_activated_post(
                                    message,
                                    db=db,
                                    telegram_id=telegram_id,
                                    pack_emoji=pack.emoji,
                                    pack_name=pack.name,
                                    remaining_display=remaining_display,
                                )
                            except Exception:
                                logger.exception(
                                    "pack_activated_message_keyboard_error",
                                    extra={"telegram_id": telegram_id, "pack_id": pack_id},
                                )
                                fallback_text = (
                                    f"🎉 Поздравляем! Пакет {pack.emoji} {pack.name} активирован.\n\n"
                                    f"Осталось фото: {remaining_display}"
                                )
                                await message.answer(
                                    fallback_text,
                                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                        [InlineKeyboardButton(text=t("nav.btn.menu", "📋 В меню"), callback_data="nav:menu")],
                                    ]),
                                )
                    elif payment_obj:
                        await message.answer("✅ Платёж уже обработан.")
                    else:
                        await message.answer(f"⚠️ Ошибка обработки. Обратитесь в поддержку: @{settings.support_username}.")

                elif payload.startswith("yoomoney_session:"):
                    parts = payload.split(":")
                    if len(parts) < 2:
                        await message.answer(f"⚠️ Ошибка обработки. Обратитесь в поддержку: @{settings.support_username}.")
                        return
                    pack_id = parts[1]
                    analytics_session_id = parts[2] if len(parts) > 2 else None
                    amount_kopecks = payment_info.total_amount
                    payment_obj, session, trial_flag, attached_free_takes = payment_service.process_session_purchase_yoomoney(
                        telegram_user_id=telegram_id,
                        provider_payment_charge_id=provider_charge_id or charge_id,
                        pack_id=pack_id,
                        amount_kopecks=amount_kopecks,
                        payload=payload,
                    )
                    if trial_flag == "trial_already_used":
                        logger.warning(
                            "yoomoney_trial_already_used_manual_refund_needed",
                            extra={
                                "telegram_id": telegram_id,
                                "charge_id": charge_id,
                                "provider_charge_id": provider_charge_id,
                                "pack_id": pack_id,
                                "amount_kopecks": amount_kopecks,
                            },
                        )
                        await message.answer(
                            t("payment.trial_refunded_yoomoney", f"Пробный пакет уже был использован. Обратитесь в поддержку: @{settings.support_username} — мы вернём средства на карту."),
                            reply_markup=main_menu_keyboard(),
                        )
                        return
                    if payment_obj and session:
                        pack = payment_service.get_pack(pack_id)
                        user = db.query(User).filter(User.telegram_id == telegram_id).one_or_none()
                        if user:
                            ProductAnalyticsService(db).track_payment_event(
                                "pay_success",
                                user.id,
                                method="yoomoney",
                                session_id=analytics_session_id or session.id,
                                pack_id=pack_id,
                                price=float(getattr(pack, "stars_price", 0) or 0),
                                price_rub=round((amount_kopecks or 0) / 100, 2),
                                currency="RUB",
                                source_component="bot",
                                properties={
                                    "charge_id": charge_id,
                                    "provider_charge_id": provider_charge_id,
                                },
                            )
                            pay_success_total.labels(pack_id=pack_id, payment_method="yoomoney").inc()
                            ProductAnalyticsService(db).track(
                                "yoomoney_payment_succeeded",
                                user.id,
                                pack_id=pack_id,
                                properties={"amount_kopecks": amount_kopecks},
                            )
                        remaining_display = session.takes_limit if (attached_free_takes and attached_free_takes > 0) else (session.takes_limit - session.takes_used)
                        is_collection = getattr(pack, "pack_subtype", "standalone") == "collection" and pack.playlist
                        if is_collection:
                            await state.set_state(BotStates.waiting_for_photo)
                            await message.answer(
                                f"✅ Коллекция {pack.emoji} {pack.name} активирована!\n\n"
                                f"Отправьте одно фото — по нему будут созданы все фото коллекции.",
                                reply_markup=main_menu_keyboard(),
                            )
                        else:
                            try:
                                await _send_pack_activated_post(
                                    message,
                                    db=db,
                                    telegram_id=telegram_id,
                                    pack_emoji=pack.emoji,
                                    pack_name=pack.name,
                                    remaining_display=remaining_display,
                                )
                            except Exception:
                                logger.exception(
                                    "pack_activated_message_keyboard_error",
                                    extra={"telegram_id": telegram_id, "pack_id": pack_id},
                                )
                                fallback_text = (
                                    f"🎉 Поздравляем! Пакет {pack.emoji} {pack.name} активирован.\n\n"
                                    f"Осталось фото: {remaining_display}"
                                )
                                await message.answer(
                                    fallback_text,
                                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                        [InlineKeyboardButton(text=t("nav.btn.menu", "📋 В меню"), callback_data="nav:menu")],
                                    ]),
                                )
                    elif payment_obj:
                        await message.answer("✅ Платёж уже обработан.")
                    else:
                        await message.answer(f"⚠️ Ошибка обработки. Обратитесь в поддержку: @{settings.support_username}.")
                    return

                elif payload.startswith("upgrade:"):
                    parts = payload.split(":")
                    if len(parts) < 3:
                        await message.answer(f"⚠️ Ошибка обработки. Обратитесь в поддержку: @{settings.support_username}.")
                        return
                    new_pack_id, old_session_id = parts[1], parts[2]
                    payment_obj, new_session = payment_service.process_session_upgrade(
                        telegram_user_id=telegram_id,
                        telegram_payment_charge_id=charge_id,
                        provider_payment_charge_id=provider_charge_id,
                        new_pack_id=new_pack_id,
                        old_session_id=old_session_id,
                        stars_amount=payment_info.total_amount,
                        payload=payload,
                    )
                    if payment_obj and new_session:
                        pack = payment_service.get_pack(new_pack_id)
                        user = db.query(User).filter(User.telegram_id == telegram_id).one_or_none()
                        hd_svc = HDBalanceService(db)
                        balance = hd_svc.get_balance(user) if user else {"total": 0}

                        audit.log(
                            actor_type="user",
                            actor_id=telegram_id,
                            action="trial_to_studio_upgrade_success",
                            entity_type="payment",
                            entity_id=charge_id,
                            payload={"new_pack_id": new_pack_id, "old_session_id": old_session_id},
                        )
                        if user:
                            ProductAnalyticsService(db).track_payment_event(
                                "pay_success",
                                user.id,
                                method="stars",
                                # For upgrade funnel consistency pay_success must stay on the pre-upgrade session.
                                session_id=old_session_id,
                                pack_id=new_pack_id,
                                price=float(payment_info.total_amount or 0),
                                price_rub=round((payment_info.total_amount or 0) * getattr(settings, "star_to_rub", 1.3), 2),
                                currency="XTR",
                                source_component="bot",
                                properties={
                                    "charge_id": charge_id,
                                    "provider_charge_id": provider_charge_id,
                                },
                            )
                        pay_success_total.labels(pack_id=new_pack_id, payment_method="stars").inc()
                        payment_amount_stars_total.labels(pack_id=new_pack_id).inc(payment_info.total_amount)

                        remaining = new_session.takes_limit - new_session.takes_used
                        await message.answer(
                            f"⬆️ Апгрейд до {pack.emoji} {pack.name}!\n\n"
                            f"Осталось фото: {remaining}\n\n"
                            f"Продолжайте!",
                            reply_markup=main_menu_keyboard(),
                        )
                    elif payment_obj:
                        await message.answer("✅ Платёж уже обработан.")
                    else:
                        await message.answer(f"⚠️ Ошибка обработки. Обратитесь в поддержку: @{settings.support_username}.")

            return

        # Legacy token-based flow
        with get_db_session() as db:
            payment_service = PaymentService(db)
            full_payload = payment_service.resolve_payload(payload)
            parsed = PaymentService.parse_payload(full_payload)
        pack_id = parsed.get("pack_id", "")
        job_id_unlock = parsed.get("job_id")
        analytics_session_id = parsed.get("session_id")

        if not pack_id and not job_id_unlock:
            logger.warning("successful_payment_invalid_payload", extra={"telegram_id": telegram_id, "charge_id": charge_id})
            await message.answer(t("payment.unknown_order", f"Не удалось определить заказ по платежу. Напишите @{settings.support_username} и укажите время платежа — разберём вручную."))
            return

        unlock_delivery_context = None  # (job_id, telegram_id, output_path, user_id, cost, charge_id) — доставка после commit
        payment_committed = False  # для except: рефанд только если платёж не сохраняли
        try:
            with get_db_session() as db:
                payment_service = PaymentService(db)
                user_service = UserService(db)
                audit = AuditService(db)

                if pack_id == "unlock":
                    # Разблокировка фото: проверка владельца и наличия файла до credit_tokens
                    user = user_service.get_by_telegram_id(telegram_id)
                    job = db.query(Job).filter(Job.job_id == job_id_unlock).one_or_none()
                    if not job or not user or job.user_id != user.id:
                        logger.warning(
                            "unlock_payment_owner_mismatch",
                            extra={"job_id": job_id_unlock, "telegram_id": telegram_id, "charge_id": charge_id},
                        )
                        try:
                            await bot.refund_star_payment(
                                user_id=message.from_user.id,
                                telegram_payment_charge_id=charge_id,
                            )
                        except Exception:
                            logger.exception("unlock_refund_failed", extra={"charge_id": charge_id})
                        await message.answer(
                            t("payment.unlock_refunded", "Ошибка заказа. Средства возвращены."),
                            reply_markup=main_menu_keyboard(),
                        )
                        return
                    elif not job.output_path_original:
                        logger.warning(
                            "unlock_payment_file_not_ready_refunding",
                            extra={"job_id": job_id_unlock, "telegram_id": telegram_id, "charge_id": charge_id},
                        )
                        try:
                            await bot.refund_star_payment(
                                user_id=message.from_user.id,
                                telegram_payment_charge_id=charge_id,
                            )
                            await message.answer(
                                t("payment.unlock_file_not_ready_refunded", f"Файл ещё не готов. Средства возвращены на ваш счёт Stars. Попробуйте разблокировать позже или напишите @{settings.support_username}."),
                                reply_markup=main_menu_keyboard(),
                            )
                        except Exception:
                            logger.exception("unlock_refund_failed", extra={"charge_id": charge_id})
                            await message.answer(
                                t("payment.unlock_file_not_ready", f"Оплата принята, но файл ещё не готов. Обратитесь в поддержку: @{settings.support_username} — мы вернём средства вручную."),
                                reply_markup=main_menu_keyboard(),
                            )
                        return
                    if getattr(job, "unlocked_at", None) or payment_service.has_unlock_payment_for_job(job_id_unlock):
                        logger.warning(
                            "unlock_payment_already_unlocked",
                            extra={"job_id": job_id_unlock, "telegram_id": telegram_id, "charge_id": charge_id},
                        )
                        try:
                            await bot.refund_star_payment(
                                user_id=message.from_user.id,
                                telegram_payment_charge_id=charge_id,
                            )
                        except Exception:
                            logger.exception("unlock_refund_failed", extra={"charge_id": charge_id})
                        await message.answer(
                            t("payment.unlock_already_refunded", "Фото уже разблокировано. Средства возвращены на ваш счёт Stars."),
                            reply_markup=main_menu_keyboard(),
                        )
                        return
                    cost = settings.unlock_cost_stars
                    payment = payment_service.credit_tokens(
                        telegram_user_id=telegram_id,
                        telegram_payment_charge_id=charge_id,
                        provider_payment_charge_id=provider_charge_id,
                        pack_id="unlock",
                        stars_amount=cost,
                        tokens_granted=0,  # не начисляем токены при unlock
                        payload=payload,
                        job_id=job_id_unlock,
                    )
                    if not payment:
                        await message.answer(
                            t("payment.credit_error", f"⚠️ Оплата получена, но произошла ошибка начисления.\nОбратитесь в поддержку: @{settings.support_username} — мы решим вопрос."),
                            reply_markup=main_menu_keyboard(),
                        )
                        return
                    unlock_delivery_context = (
                        job_id_unlock,
                        telegram_id,
                        job.output_path_original,
                        user.id,
                        cost,
                        charge_id,
                        analytics_session_id,
                    )
                else:
                    # Покупка пакета генераций
                    pack = payment_service.get_pack(pack_id)
                    if not pack:
                        logger.error("payment_pack_not_found", extra={"pack_id": pack_id})
                        await message.answer(t("payment.pack_not_found", f"Ошибка: пакет не найден. Обратитесь в поддержку: @{settings.support_username}."))
                        return

                    payment = payment_service.credit_tokens(
                        telegram_user_id=telegram_id,
                        telegram_payment_charge_id=charge_id,
                        provider_payment_charge_id=provider_charge_id,
                        pack_id=pack.id,
                        stars_amount=pack.stars_price,
                        tokens_granted=pack.tokens,
                        payload=payload,
                    )

                    if payment:
                        user = user_service.get_by_telegram_id(telegram_id)
                        balance = user.token_balance if user else "?"
                        await message.answer(
                            tr(
                                "payment.pack_success",
                                "✅ Пакет *{emoji} {name}* активирован!\n\nНачислено: *{tokens}* фото\nВаш баланс: *{balance}* фото\n\nТеперь ваши фото будут без водяного знака!",
                                emoji=pack.emoji,
                                name=pack.name,
                                tokens=pack.tokens,
                                balance=balance,
                            ),
                            parse_mode="Markdown",
                            reply_markup=main_menu_keyboard(),
                        )
                        audit.log(
                            actor_type="user",
                            actor_id=telegram_id,
                            action="payment_pack",
                            entity_type="payment",
                            entity_id=charge_id,
                            payload={"pack_id": pack.id, "stars": pack.stars_price, "tokens": pack.tokens},
                        )
                        if user:
                            active_session = SessionService(db).get_active_session(user.id)
                            ProductAnalyticsService(db).track_payment_event(
                                "pay_success",
                                user.id,
                                method="stars",
                                session_id=active_session.id if active_session else None,
                                pack_id=pack.id,
                                price=float(pack.stars_price or 0),
                                price_rub=round((pack.stars_price or 0) * getattr(settings, "star_to_rub", 1.3), 2),
                                currency="XTR",
                                source_component="bot",
                                properties={
                                    "tokens_granted": pack.tokens,
                                    "charge_id": charge_id,
                                    "provider_charge_id": provider_charge_id,
                                },
                            )
                        pay_success_total.labels(pack_id=pack.id, payment_method="stars").inc()
                        payment_amount_stars_total.labels(pack_id=pack.id).inc(pack.stars_price or 0)
                        logger.info(
                            "pack_payment_completed",
                            extra={
                                "user": telegram_id,
                                "pack": pack.id,
                                "stars": pack.stars_price,
                                "tokens": pack.tokens,
                                "charge_id": charge_id,
                            },
                        )

                        # Referral: mark wow-moment + create bonus for referrer
                        if user and not getattr(user, "has_purchased_hd", False):
                            user.has_purchased_hd = True
                            db.add(user)

                        # Legacy purchase-based referral bonuses are disabled.

                    else:
                        await message.answer(
                            t("payment.credit_error", f"⚠️ Оплата получена, но произошла ошибка начисления.\nОбратитесь в поддержку: @{settings.support_username} — мы решим вопрос."),
                            reply_markup=main_menu_keyboard(),
                        )
        finally:
            payment_committed = True

        if unlock_delivery_context:
            (job_id_unlock, _telegram_id, output_path, user_id, cost, charge_id, analytics_session_id) = unlock_delivery_context
            from app.services.telegram.client import TelegramClient as TgClientUnlock
            tg = TgClientUnlock()
            try:
                tg.send_document(
                    int(_telegram_id),
                    output_path,
                    caption=t("success.unlock_caption", "🔓 Фото разблокировано! Вот ваше фото в полном качестве (без сжатия)."),
                    reply_markup={
                        "inline_keyboard": [
                            [
                                {"text": t("success.btn.menu", "📋 В меню"), "callback_data": "success_action:menu"},
                                {"text": t("success.btn.more", "🔄 Сделать ещё"), "callback_data": "success_action:more"},
                            ]
                        ]
                    },
                )
                with get_db_session() as db2:
                    job = db2.query(Job).filter(Job.job_id == job_id_unlock).one_or_none()
                    if job:
                        job.is_preview = False
                        job.unlocked_at = datetime.now(timezone.utc)
                        job.unlock_method = "stars"
                        db2.add(job)
                    paywall_record_unlock(
                        job_id=job_id_unlock,
                        user_id=user_id,
                        method="stars",
                        price_stars=cost,
                        price_tokens=0,
                        pack_id="unlock",
                        receipt_id=charge_id,
                        preview_to_pay_latency_seconds=None,
                    )
                    audit2 = AuditService(db2)
                    audit2.log(
                        actor_type="user",
                        actor_id=_telegram_id,
                        action="payment_unlock",
                        entity_type="payment",
                        entity_id=charge_id,
                        payload={"job_id": job_id_unlock, "stars": cost},
                    )
                    ProductAnalyticsService(db2).track_payment_event(
                        "pay_success",
                        user_id,
                        method="stars",
                        session_id=analytics_session_id,
                        pack_id="unlock",
                        price=float(cost or 0),
                        price_rub=round((cost or 0) * getattr(settings, "star_to_rub", 1.3), 2),
                        currency="XTR",
                        source_component="bot",
                        properties={
                            "job_id": job_id_unlock,
                            "charge_id": charge_id,
                        },
                    )
                    pay_success_total.labels(pack_id="unlock", payment_method="stars").inc()
                    payment_amount_stars_total.labels(pack_id="unlock").inc(cost)
                logger.info(
                    "unlock_payment_completed",
                    extra={"user": _telegram_id, "job_id": job_id_unlock, "charge_id": charge_id},
                )
            except Exception:
                logger.exception(
                    "unlock_delivery_failed",
                    extra={"job_id": job_id_unlock, "charge_id": charge_id, "telegram_id": _telegram_id},
                )
                await message.answer(
                    t("payment.unlock_send_error", f"Оплата принята. Не удалось отправить фото — напишите в поддержку: @{settings.support_username}."),
                    reply_markup=main_menu_keyboard(),
                )
            finally:
                tg.close()

    except Exception:
        logger.exception("Error in successful_payment", extra={"charge_id": charge_id})
        if not payment_committed and not payload.startswith("yoomoney_session:"):
            try:
                await bot.refund_star_payment(
                    user_id=message.from_user.id,
                    telegram_payment_charge_id=charge_id,
                )
                logger.info(
                    "payment_failed_refund_attempt",
                    extra={"charge_id": charge_id, "telegram_id": getattr(message.from_user, "id", None)},
                )
            except Exception as ref_e:
                logger.exception(
                    "payment_failed_refund_error",
                    extra={"charge_id": charge_id, "error": str(ref_e)},
                )
        await message.answer(
            t("payment.generic_error", f"⚠️ Произошла ошибка при обработке платежа.\nОбратитесь в поддержку: @{settings.support_username}."),
            reply_markup=main_menu_keyboard(),
        )


# ===========================================
# Команды поддержки платежей (требование Telegram)
# ===========================================

@payments_router.message(Command("paysupport"))
async def cmd_paysupport(message: Message):
    """Поддержка по платежам (требование Telegram для ботов с оплатой)."""
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
                    ProductAnalyticsService(db).track("button_click", user.id, properties={"button_id": "paysupport"})
            except Exception:
                logger.exception("button_click track failed paysupport")
        await message.answer(
            t(
                "cmd.paysupport",
                "💬 Поддержка NeoBanana\n\n"
                "Есть вопросы или что-то не так?\n\n"
                "Поможем с:\n"
                "• качеством фото\n"
                "• оплатой (включая ЮMoney)\n"
                "• генерациями\n\n"
                "Просто напишите нам 👇\n"
                f"@{settings.support_username}",
            ),
            reply_markup=main_menu_keyboard(),
        )
    except Exception:
        logger.exception("Error in cmd_paysupport")
        await message.answer(t("errors.try_later", "Произошла ошибка. Попробуйте позже."))


@payments_router.message(Command("terms"))
async def cmd_terms(message: Message):
    """Условия использования (требование Telegram для ботов с оплатой)."""
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
                    ProductAnalyticsService(db).track("button_click", user.id, properties={"button_id": "terms"})
            except Exception:
                logger.exception("button_click track failed terms")
        await message.answer(
            t(
                "cmd.terms",
                "📄 *Условия использования NeoBanana*\n\n"
                "1. Пакеты фото приобретаются через ЮMoney.\n"
                "2. Бесплатные превью — с водяным знаком.\n"
                "3. Оплаченный пакет даёт фото в полном качестве без водяного знака.\n"
                "4. По вопросам возврата обратитесь в поддержку.\n"
                "5. Администрация вправе отказать в обслуживании при нарушении правил.\n"
                "6. Все сгенерированные изображения — результат работы ИИ.\n\n"
                "Используя бота, вы соглашаетесь с этими условиями.",
            ),
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
    except Exception:
        logger.exception("Error in cmd_terms")
        await message.answer(t("errors.try_later", "Произошла ошибка. Попробуйте позже."))
