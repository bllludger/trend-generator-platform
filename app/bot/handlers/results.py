import logging
import os
from uuid import uuid4

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from sqlalchemy.orm import Session

from app.bot.states import BotStates
from app.bot.helpers import t, tr, get_db_session, _escape_markdown, _has_paid_profile, logger
from app.bot.keyboards import main_menu_keyboard, _feedback_keyboard, _negative_reason_keyboard, themes_keyboard
from app.bot.constants import (
    TREND_CUSTOM_ID, DEFAULT_ASPECT_RATIO, GENERATION_NEGATIVE_REASONS,
    MONEY_IMAGE_PATH, PAYMENT_SUCCESS_IMAGE_PATH,
)
from app.core.config import settings
from app.constants import AUDIENCE_WOMEN
from app.services.users.service import UserService
from app.services.sessions.service import SessionService
from app.services.takes.service import TakeService
from app.services.trends.service import TrendService
from app.services.themes.service import ThemeService
from app.services.audit.service import AuditService
from app.services.product_analytics.service import ProductAnalyticsService
from app.services.favorites.service import FavoriteService
from app.services.hd_balance.service import HDBalanceService
from app.services.payments.service import PaymentService, PRODUCT_LADDER_IDS
from app.services.trial_v2.service import TrialV2Service
from app.services.balance_tariffs import build_balance_tariffs_message, get_balance_line, _pack_outcome_label
from app.services.idempotency import IdempotencyStore
from app.services.unlock_order.service import UnlockOrderService, unlock_photo_display_filename, validate_can_create_unlock
from app.services.yookassa.client import YooKassaClient, YooKassaClientError
from app.models.user import User
from app.models.pack import Pack
from app.models.session import Session as SessionModel
from app.models.take import Take as TakeModel
from app.models.trend import Trend as TrendModel
from app.paywall import record_unlock as paywall_record_unlock
from app.utils.metrics import favorite_selected_total, paywall_viewed_total, pay_initiated_total
from app.utils.currency import format_stars_rub
from app.utils.telegram_photo import path_for_telegram_photo

results_router = Router()


@results_router.callback_query(F.data.startswith("choose:"))
async def choose_variant(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """User chose best variant A/B/C — auto-add to favorites."""
    telegram_id = str(callback.from_user.id)
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("❌ Ошибка формата", show_alert=True)
        return
    take_id, variant = parts[1], parts[2].upper()
    if variant not in ("A", "B", "C"):
        await callback.answer("❌ Неверный вариант", show_alert=True)
        return

    try:
        with get_db_session() as db:
            take_svc = TakeService(db)
            fav_svc = FavoriteService(db)
            audit = AuditService(db)
            user_service = UserService(db)

            take = take_svc.get_take(take_id)
            if not take:
                await callback.answer("❌ Фото не найдено", show_alert=True)
                return

            user = user_service.get_or_create_user(
                telegram_id,
                telegram_username=callback.from_user.username,
                telegram_first_name=callback.from_user.first_name,
                telegram_last_name=callback.from_user.last_name,
            )
            if str(take.user_id) != str(user.id):
                await callback.answer("❌ Нет доступа к этому фото", show_alert=True)
                return

            preview_path, original_path = take_svc.get_variant_paths(take, variant)
            if not preview_path or not original_path:
                await callback.answer("❌ Вариант недоступен", show_alert=True)
                return

            fav = fav_svc.add_favorite(
                user_id=user.id,
                take_id=take_id,
                variant=variant,
                preview_path=preview_path,
                original_path=original_path,
                session_id=take.session_id,
            )

            audit.log(
                actor_type="user",
                actor_id=telegram_id,
                action="choose_best_variant",
                entity_type="take",
                entity_id=take_id,
                payload={
                    "variant": variant,
                    "session_id": take.session_id,
                    "favorite_id": fav.id if fav else None,
                    "trend_id": getattr(take, "trend_id", None),
                },
            )
            audit.log(
                actor_type="user",
                actor_id=telegram_id,
                action="favorites_auto_add",
                entity_type="favorite",
                entity_id=fav.id if fav else None,
                payload={
                    "take_id": take_id,
                    "variant": variant,
                    "trend_id": getattr(take, "trend_id", None),
                },
            )
            variant_position = {"A": 1, "B": 2, "C": 3}.get(variant, 0)
            _trend_id = getattr(take, "trend_id", None)
            analytics = ProductAnalyticsService(db)
            analytics.track_button_click(
                user.id,
                button_id=f"variant_{variant.lower()}",
                session_id=take.session_id,
                source_component="bot",
                take_id=take_id,
                trend_id=_trend_id,
            )
            analytics.track_funnel_step(
                "favorite_selected",
                user.id,
                session_id=take.session_id,
                trend_id=_trend_id,
                take_id=take_id,
                source_component="bot",
                properties={"variant_id": variant, "variant_position": variant_position},
            )
            favorite_selected_total.inc()
            if _trend_id:
                analytics.track(
                    "trend_favorite_selected",
                    user.id,
                    session_id=take.session_id,
                    trend_id=_trend_id,
                    take_id=take_id,
                    properties={"variant_id": variant, "variant_position": variant_position},
                )
            session_id = take.session_id
            user_is_moderator = getattr(user, "is_moderator", False)
            session_svc = SessionService(db)
            active_session = session_svc.get_active_session(user.id)
            has_active_paid_package = _has_paid_profile(user, active_session)
            fav_id = str(fav.id) if fav else None
            hd_svc = HDBalanceService(db)
            balance = hd_svc.get_balance(user)

            trend_label = "Фото"
            if getattr(take, "trend_id", None):
                trend = TrendService(db).get(take.trend_id)
                if trend:
                    trend_label = f"{trend.emoji} {trend.name}"

        await callback.answer(f"⭐ Добавлено: {trend_label}, вариант {variant}")

        is_free = False
        if session_id:
            with get_db_session() as db:
                session_svc = SessionService(db)
                session = session_svc.get_session(session_id)
                if session and session.pack_id == "free_preview":
                    is_free = True

        if (is_free or not session_id) and not user_is_moderator and not has_active_paid_package:
            # Оплата по ссылке ЮKassa за разблокировку одного фото (вариант A/B/C)
            yookassa = YooKassaClient()
            if not yookassa.is_configured():
                logger.info(
                    "choose_variant_yookassa_not_configured",
                    extra={"telegram_id": telegram_id, "take_id": take_id, "variant": variant},
                )
                await callback.message.answer(
                    "⚠️ Возникла временная ошибка при оплате.\n\n"
                    "Мы уже исправляем её.\n\n"
                    "Нажмите «Помощь» —\n"
                    "поддержка ответит оперативно\n"
                    "и поможет завершить оплату.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🆘 Помощь", callback_data="profile:support")],
                        [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
                    ]),
                )
                return
            # Чистый переход: только ссылка на оплату, без меню тарифов
            with get_db_session() as db:
                    ok, err = validate_can_create_unlock(db, telegram_id, take_id, variant)
                    if not ok:
                        await callback.message.answer(f"❌ {err}")
                        return
                    unlock_svc = UnlockOrderService(db)
                    existing_paid = unlock_svc.get_order_with_paid_or_delivered(telegram_id, take_id, variant)
                    if existing_paid:
                        take_for_path = TakeService(db).get_take(take_id)
                        sent = False
                        if take_for_path:
                            _, original_path = TakeService(db).get_variant_paths(take_for_path, variant)
                            if original_path and os.path.exists(original_path):
                                from app.services.telegram.client import TelegramClient as TgClient
                                tg = TgClient()
                                try:
                                    from app.services.unlock_order.service import unlock_photo_display_filename
                                    tg.send_document(
                                        int(telegram_id),
                                        original_path,
                                        caption=(
                                            "🎉 Отличный выбор!\n\n"
                                            "Вот ваш снимок\n"
                                            "без водяных знаков\n"
                                            "и в полном качестве.\n\n"
                                            "Сохраните его —\n"
                                            "он идеально подойдёт\n"
                                            "для соцсетей."
                                        ),
                                        filename=unlock_photo_display_filename(existing_paid.id, original_path),
                                    )
                                    sent = True
                                finally:
                                    tg.close()
                        if sent:
                            await callback.message.answer(
                                "Фото уже разблокировано. Отправили ещё раз в чат.",
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
                                ]),
                            )
                        else:
                            await callback.message.answer(
                                "Файл временно недоступен. Попробуйте нажать «Получить фото снова» позже.",
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(text="🔄 Получить фото снова", callback_data=f"unlock_resend:{existing_paid.id}")],
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
                        await callback.message.answer("⏳ Уже создаём ссылку на оплату. Подождите пару секунд.")
                        return
                    order, is_new = unlock_svc.create_or_get_pending_order(telegram_id, take_id, variant)
                    if not is_new and order.confirmation_url:
                        if create_lock is not None and lock_acquired:
                            try:
                                create_lock.release(create_lock_key)
                            except Exception:
                                pass
                        await callback.message.answer(
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
                        logger.info(
                            "choose_variant_no_bot_username",
                            extra={"telegram_id": telegram_id, "take_id": take_id},
                        )
                        await callback.message.answer(
                            "⚠️ Возникла временная ошибка при оплате.\n\n"
                            "Мы уже исправляем её.\n\n"
                            "Нажмите «Помощь» —\n"
                            "поддержка ответит оперативно\n"
                            "и поможет завершить оплату.",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="🆘 Помощь", callback_data="profile:support")],
                                [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
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
                    except YooKassaClientError as e:
                        if create_lock is not None and lock_acquired:
                            try:
                                create_lock.release(create_lock_key)
                            except Exception:
                                pass
                        logger.warning("yookassa_create_payment_failed", extra={"order_id": order.id, "error": str(e)})
                        await callback.message.answer(
                            "⚠️ Возникла временная ошибка при оплате.\n\n"
                            "Мы уже исправляем её.\n\n"
                            "Нажмите «Помощь» —\n"
                            "поддержка ответит оперативно\n"
                            "и поможет завершить оплату.",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="🆘 Помощь", callback_data="profile:support")],
                                [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
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
                        logger.warning(
                            "yookassa_missing_confirmation_url",
                            extra={"order_id": order.id, "has_url": bool(confirmation_url), "has_id": bool(yookassa_payment_id)},
                        )
                        await callback.message.answer(
                            "⚠️ Возникла временная ошибка при оплате.\n\n"
                            "Мы уже исправляем её.\n\n"
                            "Нажмите «Помощь» —\n"
                            "поддержка ответит оперативно\n"
                            "и поможет завершить оплату.",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="🆘 Помощь", callback_data="profile:support")],
                                [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
                            ]),
                        )
                        return
                    unlock_svc.set_payment_created(
                        order.id,
                        yookassa_payment_id,
                        confirmation_url,
                        idempotence_key,
                    )
                    logger.info(
                        "choose_variant_yookassa_link_sent",
                        extra={"telegram_id": telegram_id, "order_id": order.id, "take_id": take_id, "variant": variant},
                    )
                    await callback.message.answer(
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
        else:
            await state.set_state(BotStates.viewing_take_result)
            await state.update_data(current_take_id=take_id)
            hd_buttons = []
            if fav_id:
                hd_buttons.append([InlineKeyboardButton(text="💎 Открыть выбранное фото", callback_data=f"deliver_hd_one:{fav_id}")])
            else:
                hd_buttons.append([InlineKeyboardButton(text="📋 Избранное", callback_data="open_favorites")])
            hd_buttons.append([InlineKeyboardButton(text="📦 Забрать все 3 в 4K", callback_data=f"return_all_hq:{take_id}")])
            await callback.message.answer(
                "Отлично. Можно открыть этот вариант в полном качестве (4K) без водяного знака.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=hd_buttons),
            )

    except Exception:
        logger.exception("choose_variant error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка. Попробуйте снова.", show_alert=True)


@results_router.callback_query(F.data.startswith("return_all_hq:"))
async def return_all_hq_variants(callback: CallbackQuery):
    """Return all available A/B/C originals in best quality for paid users."""
    telegram_id = str(callback.from_user.id)
    parts = (callback.data or "").split(":", 1)
    if len(parts) != 2:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    take_id = (parts[1] or "").strip()
    if not take_id:
        await callback.answer("❌ Ошибка", show_alert=True)
        return

    try:
        idem_key = f"return_all_hq:{telegram_id}:{take_id}"
        try:
            if not IdempotencyStore().check_and_set(idem_key, ttl_seconds=20):
                await callback.answer("⏳ Уже отправляю варианты…")
                return
        except Exception:
            logger.warning("return_all_hq_idempotency_unavailable", extra={"user_id": telegram_id, "take_id": take_id})
        await callback.answer("📦 Отправляю все варианты в лучшем качестве…")

        with get_db_session() as db:
            user = UserService(db).get_by_telegram_id(telegram_id)
            take = TakeService(db).get_take(take_id)
            if not user or not take or str(take.user_id) != str(user.id):
                await callback.message.answer("Нет доступа к этому набору.")
                return

            session_svc = SessionService(db)
            take_session = session_svc.get_session(take.session_id) if take.session_id else None
            active_session = session_svc.get_active_session(user.id)
            has_active_paid_package = bool(
                (take_session and (str(take_session.pack_id or "").strip().lower() != "free_preview"))
                or _has_paid_profile(user, active_session)
            )
            if not has_active_paid_package:
                await callback.message.answer("Эта функция доступна платным пользователям.")
                return

            take_svc = TakeService(db)
            originals: list[tuple[str, str]] = []
            for variant in ("A", "B", "C"):
                _, original_path = take_svc.get_variant_paths(take, variant)
                if original_path and os.path.isfile(original_path):
                    originals.append((variant, original_path))

        if not originals:
            await callback.message.answer("Оригиналы пока недоступны.")
            return

        for idx, (variant, path) in enumerate(originals):
            caption = f"🖼 Вариант {variant} — лучшее качество, без водяного знака."
            if idx == 0:
                caption = "📦 Возвращаю все 3 в лучшем качестве.\n\n" + caption
            await callback.message.answer_document(
                document=FSInputFile(path),
                caption=caption,
            )

        await callback.message.answer(
            "Готово. Что делаем дальше?",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="↩️ Вернуться к трендам", callback_data="post_hd:trends")],
                    [InlineKeyboardButton(text="🔥 Создать фото", callback_data="post_hd:create")],
                ]
            ),
        )

    except Exception:
        logger.exception("return_all_hq_variants error", extra={"user_id": telegram_id})
        await callback.message.answer("Не удалось отправить. Попробуйте позже.")


def _pack_activated_message_and_keyboard(
    db: Session,
    telegram_id: str,
    pack_emoji: str,
    pack_name: str,
    remaining_display: int,
) -> tuple[str, InlineKeyboardMarkup]:
    """Текст и клавиатура после активации пакета."""
    user = db.query(User).filter(User.telegram_id == telegram_id).one_or_none()
    pack_tokens = None
    pack = db.query(Pack).filter(Pack.name == pack_name).one_or_none()
    if pack and getattr(pack, "tokens", None) is not None:
        try:
            pack_tokens = int(pack.tokens)
        except Exception:
            pack_tokens = None
    if pack_tokens is None:
        pack_tokens = int(remaining_display or 0)
    base_text = (
        f"🎉 Пакет {pack_name} активирован\n\n"
        "Вам доступно:\n"
        f"• {pack_tokens} фото для создания образов\n"
        "• возможность пересоздавать результат\n"
        "• фото без водяных знаков\n"
        "• максимальное качество"
    )
    rows = []
    if user:
        fav_svc = FavoriteService(db)
        last_pending = fav_svc.get_last_pending_hd_favorite(user.id)
        if last_pending:
            rows.append([
                InlineKeyboardButton(text="💎 Открыть выбранное фото", callback_data=f"deliver_hd_one:{last_pending.id}"),
            ])
    rows.append([
        InlineKeyboardButton(text="🖼 Вернуться к превью", callback_data="pack:return_previews"),
    ])
    return base_text, InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_pack_activated_post(
    target: Message,
    *,
    db: Session,
    telegram_id: str,
    pack_emoji: str,
    pack_name: str,
    remaining_display: int,
) -> None:
    """Отправить пост активации пакета: с картинкой payments_yes.png (если есть) и кнопками."""
    text, keyboard = _pack_activated_message_and_keyboard(
        db=db,
        telegram_id=telegram_id,
        pack_emoji=pack_emoji,
        pack_name=pack_name,
        remaining_display=remaining_display,
    )
    if os.path.exists(PAYMENT_SUCCESS_IMAGE_PATH):
        try:
            photo_path, is_temp = path_for_telegram_photo(PAYMENT_SUCCESS_IMAGE_PATH)
            await target.answer_photo(
                photo=FSInputFile(photo_path),
                caption=text,
                reply_markup=keyboard,
            )
            if is_temp and os.path.isfile(photo_path):
                try:
                    os.unlink(photo_path)
                except OSError:
                    pass
            return
        except Exception:
            logger.exception("pack_activated_post_photo_failed", extra={"path": PAYMENT_SUCCESS_IMAGE_PATH})
    await target.answer(text, reply_markup=keyboard)


@results_router.callback_query(F.data == "pack:return_previews")
async def pack_return_previews(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """После оплаты: вернуть последний набор превью; если нет — отправить в выбор трендов."""
    telegram_id = str(callback.from_user.id)
    try:
        with get_db_session() as db:
            user = UserService(db).get_by_telegram_id(telegram_id)
            if not user:
                await callback.answer("Пользователь не найден", show_alert=True)
                return

            take = (
                db.query(TakeModel)
                .filter(
                    TakeModel.user_id == user.id,
                    TakeModel.status.in_(["ready", "partial_fail"]),
                )
                .order_by(TakeModel.created_at.desc())
                .first()
            )

            if take:
                previews = [
                    ("A", take.variant_a_preview),
                    ("B", take.variant_b_preview),
                    ("C", take.variant_c_preview),
                ]
                valid_previews = [(v, p) for v, p in previews if isinstance(p, str) and p and os.path.exists(p)]
                if len(valid_previews) >= 3:
                    input_file_id = None
                    input_local_path = None
                    if isinstance(take.input_file_ids, list) and take.input_file_ids:
                        input_file_id = take.input_file_ids[0]
                    if isinstance(take.input_local_paths, list) and take.input_local_paths:
                        input_local_path = take.input_local_paths[0]
                    if input_file_id and input_local_path and os.path.exists(input_local_path):
                        await state.update_data(
                            photo_file_id=input_file_id,
                            photo_local_path=input_local_path,
                            audience_type=(getattr(user, "flags", {}) or {}).get("audience_type") or AUDIENCE_WOMEN,
                        )
                    await state.set_state(BotStates.viewing_take_result)
                    for variant, path in valid_previews:
                        await callback.message.answer_photo(photo=FSInputFile(path), caption=f"Вариант {variant}")
                    await callback.message.answer(
                        "✨ Готово! Посмотри варианты и выбери лучший:",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="1️⃣ Выбрать первый вариант", callback_data=f"choose:{take.id}:A")],
                            [InlineKeyboardButton(text="2️⃣ Выбрать второй вариант", callback_data=f"choose:{take.id}:B")],
                            [InlineKeyboardButton(text="3️⃣ Выбрать третий вариант", callback_data=f"choose:{take.id}:C")],
                            [InlineKeyboardButton(text="🤍 Выбрать все 3", callback_data=f"trial_select:{take.id}:ALL")],
                            [InlineKeyboardButton(text="🔁 Все 3 не подходят", callback_data=f"rescue:reject_set:{take.id}")],
                        ]),
                    )
                    await callback.answer()
                    return

            # Fallback: нет готового набора превью — отправляем в выбор трендов.
            audience = AUDIENCE_WOMEN
            if take and isinstance(take.input_file_ids, list) and take.input_file_ids and isinstance(take.input_local_paths, list) and take.input_local_paths:
                input_path = take.input_local_paths[0]
                if isinstance(input_path, str) and os.path.exists(input_path):
                    await state.update_data(
                        photo_file_id=take.input_file_ids[0],
                        photo_local_path=input_path,
                        selected_trend_id=None,
                        selected_trend_name=None,
                        custom_prompt=None,
                        audience_type=audience,
                    )
                    await state.set_state(BotStates.waiting_for_trend)
                    trend_service = TrendService(db)
                    theme_service = ThemeService(db)
                    theme_ids_with_trends = trend_service.list_theme_ids_with_active_trends(audience)
                    all_themes = theme_service.list_all()
                    themes = [t for t in all_themes if t.enabled and t.id in theme_ids_with_trends]
                    themes_data = [{"id": t.id, "name": t.name, "emoji": t.emoji or ""} for t in themes]
                    await callback.message.answer(
                        t("flow.choose_other_trend", "Выберите тематику и тренд:"),
                        reply_markup=themes_keyboard(themes_data),
                    )
                    await callback.answer()
                    return

        await state.clear()
        await callback.message.answer(
            "Не нашли последний набор превью. Нажмите «🔥 Создать фото», чтобы выбрать тренд заново.",
            reply_markup=main_menu_keyboard(),
        )
        await callback.answer()
    except Exception:
        logger.exception("pack_return_previews_error", extra={"user_id": telegram_id})
        await callback.answer("Ошибка. Попробуйте позже.", show_alert=True)


async def _show_paywall_after_free_take(
    message: Message, telegram_id: str, take_id: str, variant: str, fav_id: str | None = None
):
    """Show contextual paywall after free take — all ladder packs."""
    try:
        with get_db_session() as db:
            audit = AuditService(db)
            user_svc = UserService(db)
            user = user_svc.get_by_telegram_id(telegram_id)
            session_svc = SessionService(db)
            active_session = session_svc.get_active_session(user.id) if user else None
            has_active_paid_package = _has_paid_profile(user, active_session)

            if has_active_paid_package:
                last_pending = FavoriteService(db).get_last_pending_hd_favorite(user.id) if user else None
                direct_callback = f"deliver_hd_one:{last_pending.id}" if last_pending else "open_favorites"
                await message.answer(
                    "✅ У вас уже активирован платный пакет.\nМожно сразу получить фото в 4K без доплаты.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💎 Сразу получить в 4K", callback_data=direct_callback)],
                        [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
                    ]),
                )
                return

            is_trial_eligible = user and not getattr(user, "trial_purchased", True)
            take = TakeService(db).get_take(take_id)
            session_id = take.session_id if take else None

            payment_service = PaymentService(db)
            all_packs = payment_service.list_product_ladder_packs()

            buttons_data = []
            position = 1
            from app.services.balance_tariffs import SHORT_NAMES as _short_names
            for p in all_packs:
                if getattr(p, "pack_subtype", "standalone") == "collection" and not getattr(p, "playlist", None):
                    continue
                if p.is_trial and not is_trial_eligible:
                    continue
                buttons_data.append({
                    "id": p.id, "emoji": p.emoji,
                    "name": _short_names.get(p.id, p.name), "stars_price": p.stars_price,
                    "outcome": _pack_outcome_label(p),
                    "hd_amount": getattr(p, "hd_amount", None), "position": position,
                })
                position += 1

            audit.log(
                actor_type="user",
                actor_id=telegram_id,
                action="paywall_variant_shown",
                entity_type="take",
                entity_id=take_id,
                payload={
                    "context": "free_preview",
                    "buttons": [{"pack_id": b["id"], "stars_price": b["stars_price"], "position": b["position"]} for b in buttons_data],
                },
            )
            if user:
                ProductAnalyticsService(db).track_funnel_step(
                    "paywall_viewed",
                    user.id,
                    session_id=session_id,
                    take_id=take_id,
                    source_component="bot",
                )
                paywall_viewed_total.inc()

        rate = getattr(settings, "star_to_rub", 1.3)
        buttons = []
        for bd in buttons_data:
            outcome = bd.get("outcome", "")
            label = f"{bd['emoji']} {bd['name']}: {outcome} — {format_stars_rub(bd['stars_price'], rate)}" if outcome else f"{bd['emoji']} {bd['name']} — {format_stars_rub(bd['stars_price'], rate)}"
            buttons.append([InlineKeyboardButton(text=label, callback_data=f"paywall:{bd['id']}")])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer(
            "👀 Смотри бесплатно, плати только если нравится!\n\n"
            "🎬 Получи 4K версию без водяного знака:",
            reply_markup=keyboard,
        )
        if fav_id:
            await message.answer(
                "Отлично. Можно открыть этот вариант в полном качестве (4K) без водяного знака.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💎 Открыть выбранное фото", callback_data=f"deliver_hd_one:{fav_id}")],
                ]),
            )
    except Exception:
        logger.exception("_show_paywall_after_free_take error")
        try:
            await message.answer(
                "Не удалось открыть магазин. Нажмите «🛒 Купить пакет» ещё раз."
            )
        except Exception:
            pass


@results_router.callback_query(F.data.startswith("add_var:"))
async def add_variant_to_favorites(callback: CallbackQuery, state: FSMContext):
    """Add another variant from the same Take to favorites."""
    telegram_id = str(callback.from_user.id)
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    take_id, variant = parts[1], parts[2].upper()

    try:
        with get_db_session() as db:
            take_svc = TakeService(db)
            fav_svc = FavoriteService(db)
            user_service = UserService(db)

            take = take_svc.get_take(take_id)
            if not take:
                await callback.answer("❌ Фото не найдено", show_alert=True)
                return

            user = user_service.get_or_create_user(
                telegram_id,
                telegram_username=callback.from_user.username,
                telegram_first_name=callback.from_user.first_name,
                telegram_last_name=callback.from_user.last_name,
            )

            preview_path, original_path = take_svc.get_variant_paths(take, variant)
            if not preview_path or not original_path:
                await callback.answer("❌ Вариант недоступен", show_alert=True)
                return

            fav = fav_svc.add_favorite(
                user_id=user.id,
                take_id=take_id,
                variant=variant,
                preview_path=preview_path,
                original_path=original_path,
                session_id=take.session_id,
            )

            trend_label = "Фото"
            if getattr(take, "trend_id", None):
                trend = TrendService(db).get(take.trend_id)
                if trend:
                    trend_label = f"{trend.emoji} {trend.name}"

            audit = AuditService(db)
            audit.log(
                actor_type="user",
                actor_id=telegram_id,
                action="favorites_auto_add",
                entity_type="favorite",
                entity_id=fav.id if fav else None,
                payload={
                    "take_id": take_id,
                    "variant": variant,
                    "trend_id": getattr(take, "trend_id", None),
                },
            )
            _trend_id = getattr(take, "trend_id", None)
            variant_position = {"A": 1, "B": 2, "C": 3}.get(variant, 0)
            ProductAnalyticsService(db).track(
                "favorite_selected",
                user.id,
                session_id=take.session_id,
                trend_id=_trend_id,
                take_id=take_id,
                properties={"variant_id": variant, "variant_position": variant_position},
            )
            favorite_selected_total.inc()
            if _trend_id:
                ProductAnalyticsService(db).track(
                    "trend_favorite_selected",
                    user.id,
                    session_id=take.session_id,
                    trend_id=_trend_id,
                    take_id=take_id,
                    properties={"variant_id": variant, "variant_position": variant_position},
                )

        await callback.answer(f"⭐ Добавлено: {trend_label}, вариант {variant}")
        await callback.message.answer(
            "Оцените результат:",
            reply_markup=_feedback_keyboard(take_id, variant),
        )
    except Exception:
        logger.exception("add_variant_to_favorites error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)


@results_router.callback_query(F.data.startswith("gen_fb:"))
async def generation_feedback_cb(callback: CallbackQuery):
    """Product analytics: generation_feedback (liked true/false)."""
    telegram_id = str(callback.from_user.id)
    parts = callback.data.split(":", 3)
    if len(parts) != 4:
        await callback.answer()
        return
    _prefix, take_id, variant, liked_str = parts
    liked = liked_str == "1"
    try:
        with get_db_session() as db:
            user = UserService(db).get_by_telegram_id(telegram_id)
            if user:
                ProductAnalyticsService(db).track(
                    "generation_feedback",
                    user.id,
                    take_id=take_id,
                    trend_id=None,
                    properties={"liked": liked},
                )
        await callback.answer("Спасибо за отзыв!")
    except Exception:
        logger.exception("generation_feedback_cb error", extra={"user_id": telegram_id})
        await callback.answer()


@results_router.callback_query(F.data.startswith("ln:"))
async def likeness_feedback_cb(callback: CallbackQuery):
    """Product analytics: generation_likeness_feedback (yes/no). If no, show reason buttons."""
    telegram_id = str(callback.from_user.id)
    parts = callback.data.split(":", 3)
    if len(parts) != 4:
        await callback.answer()
        return
    _prefix, take_id, variant, likeness = parts
    try:
        with get_db_session() as db:
            user = UserService(db).get_by_telegram_id(telegram_id)
            if user:
                ProductAnalyticsService(db).track(
                    "generation_likeness_feedback",
                    user.id,
                    take_id=take_id,
                    properties={"likeness": likeness},
                )
        if likeness == "no":
            await callback.message.answer(
                "Укажите причину:",
                reply_markup=_negative_reason_keyboard(take_id, variant),
            )
            await callback.answer()
        else:
            await callback.answer("Спасибо!")
    except Exception:
        logger.exception("likeness_feedback_cb error", extra={"user_id": telegram_id})
        await callback.answer()


@results_router.callback_query(F.data.startswith("nr:"))
async def negative_reason_cb(callback: CallbackQuery):
    """Product analytics: generation_negative_reason."""
    telegram_id = str(callback.from_user.id)
    parts = callback.data.split(":", 3)
    if len(parts) != 4:
        await callback.answer()
        return
    _prefix, take_id, variant, reason = parts
    try:
        with get_db_session() as db:
            user = UserService(db).get_by_telegram_id(telegram_id)
            if user:
                ProductAnalyticsService(db).track(
                    "generation_negative_reason",
                    user.id,
                    take_id=take_id,
                    properties={"reason": reason},
                )
        await callback.answer("Спасибо, учтём!")
    except Exception:
        logger.exception("negative_reason_cb error", extra={"user_id": telegram_id})
        await callback.answer()


@results_router.callback_query(F.data == "take_more")
async def take_more(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Start another Take within the session. Collection mode: auto-advance with same photo."""
    telegram_id = str(callback.from_user.id)
    try:
        with get_db_session() as db:
            user = UserService(db).get_by_telegram_id(telegram_id)
            if user:
                ProductAnalyticsService(db).track(
                    "button_click",
                    user.id,
                    properties={"button_id": "take_more"},
                )
        with get_db_session() as db:
            user_service = UserService(db)
            session_svc = SessionService(db)
            user = user_service.get_or_create_user(
                telegram_id,
                telegram_username=callback.from_user.username,
                telegram_first_name=callback.from_user.first_name,
                telegram_last_name=callback.from_user.last_name,
            )
            session = session_svc.get_active_session(user.id)

            if not session or not session_svc.can_take(session):
                if getattr(user, "is_moderator", False):
                    session = session_svc.create_free_preview_session(user.id)
                    ProductAnalyticsService(db).track("collection_started", user.id, session_id=session.id)
                else:
                    telegram_id = str(callback.from_user.id)
                    text, kb_dict = build_balance_tariffs_message(db, telegram_id)
                    if kb_dict is None:
                        await callback.message.answer("Пакеты временно недоступны.", reply_markup=main_menu_keyboard())
                        await callback.answer()
                        return
                    rows = kb_dict.get("inline_keyboard", [])
                    buttons = [
                        [InlineKeyboardButton(text=btn["text"], callback_data=btn["callback_data"]) for btn in row]
                        for row in rows
                    ]
                    if session:
                        buttons.append([InlineKeyboardButton(text="📋 Избранное", callback_data="open_favorites")])
                    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
                    if os.path.exists(MONEY_IMAGE_PATH):
                        try:
                            photo_path, is_temp = path_for_telegram_photo(MONEY_IMAGE_PATH)
                            await callback.message.answer_photo(
                                photo=FSInputFile(photo_path),
                                caption=text,
                                parse_mode="HTML",
                                reply_markup=keyboard,
                            )
                            if is_temp and os.path.isfile(photo_path):
                                try:
                                    os.unlink(photo_path)
                                except OSError:
                                    pass
                        except Exception as e:
                            logger.warning("take_more_money_photo_failed", extra={"path": MONEY_IMAGE_PATH, "error": str(e)})
                            await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
                    else:
                        await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
                    await callback.answer()
                    return

            # Collection mode: auto-advance with the same photo
            if session_svc.is_collection(session):
                trend_id = session_svc.get_next_trend_id(session)
                if not trend_id:
                    fav_svc = FavoriteService(db)
                    fav_count = fav_svc.count_favorites(session.id)
                    selected_count = fav_svc.count_selected_for_hd(session.id)
                    session_svc.complete_session(session)

                    audit = AuditService(db)
                    audit.log(
                        actor_type="system",
                        actor_id="bot",
                        action="collection_complete",
                        entity_type="session",
                        entity_id=session.id,
                        payload={
                            "collection_run_id": session.collection_run_id,
                            "total_steps": len(session.playlist),
                        },
                    )

                    await callback.message.answer(
                        f"🎉 Коллекция завершена!\n\n"
                        f"Всего превью: {session.takes_used * 3}\n"
                        f"В избранном: {fav_count} (отмечено для 4K: {selected_count})\n"
                        f"4K осталось: {session_svc.hd_remaining(session)}\n\n"
                        f"Отметьте лучшие и нажмите «Забрать 4K альбомом».",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="⭐ Открыть избранное", callback_data="open_favorites")],
                            [InlineKeyboardButton(text="🖼 Забрать 4K альбомом", callback_data="deliver_hd_album")],
                        ]),
                    )
                    await callback.answer()
                    return

                if not session.input_photo_path or not os.path.isfile(session.input_photo_path):
                    await callback.message.answer("❌ Фото для коллекции не найдено. Начните заново.")
                    await callback.answer()
                    return

                trend_svc = TrendService(db)
                trend = trend_svc.get(trend_id)
                trend_name = trend.name if trend else trend_id
                step_num = (session.current_step or 0) + 1
                total_steps = len(session.playlist)

                take_svc = TakeService(db)
                take = take_svc.create_take(
                    user_id=user.id,
                    trend_id=trend_id,
                    input_file_ids=[session.input_file_id] if session.input_file_id else [],
                    input_local_paths=[session.input_photo_path],
                    image_size="1024x1024",
                )
                take.step_index = session.current_step
                take.is_reroll = False
                db.add(take)
                session_svc.attach_take_to_session(take, session)
                session_svc.advance_step(session)
                take_id = take.id

                from app.core.celery_app import celery_app as _celery
                chat_id = str(callback.message.chat.id)

                status_msg = await callback.message.answer(
                    f"⏳ Образ {step_num} из {total_steps} — {trend_name}...",
                )
                _celery.send_task(
                    "app.workers.tasks.generate_take.generate_take",
                    args=[take_id],
                    kwargs={
                        "status_chat_id": chat_id,
                        "status_message_id": status_msg.message_id,
                    },
                )
                await callback.answer()
                return

        await state.set_state(BotStates.waiting_for_photo)
        await callback.message.answer(
            "📷 Отправьте фото для нового снимка.",
            reply_markup=main_menu_keyboard(),
        )
        await callback.answer("📸 Загрузите фото")
    except Exception:
        logger.exception("take_more error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)
