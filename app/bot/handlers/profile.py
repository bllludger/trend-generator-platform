import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.orm import Session
from app.bot.helpers import t, tr, get_db_session, _escape_markdown, _has_paid_profile, logger
from app.bot.keyboards import main_menu_keyboard, _profile_keyboard
from app.bot.constants import SUBSCRIPTION_CHANNEL_USERNAME
from app.core.config import settings
from app.services.users.service import UserService
from app.services.sessions.service import SessionService
from app.services.audit.service import AuditService
from app.services.product_analytics.service import ProductAnalyticsService
from app.services.trial_v2.service import TrialV2Service
from app.referral.service import ReferralService
from app.models.user import User
from app.models.pack import Pack
from app.models.session import Session as SessionModel

profile_router = Router()


def _build_profile_view(db: Session, user: User, active_session: SessionModel | None) -> tuple[str, InlineKeyboardMarkup, bool]:
    """Единый рендер профиля: счётчики и кнопки для paid/free сценариев."""
    text = t("profile.title", "👤 *Мой профиль*") + "\n\n"
    is_paid_active = False
    has_remaining = False
    is_trial_profile = False
    if active_session:
        _pack = db.query(Pack).filter(Pack.id == active_session.pack_id).one_or_none()
        pack_id_norm = str(active_session.pack_id or "").strip().lower()
        plan_name = _pack.name if _pack else ("Бесплатный" if pack_id_norm == "free_preview" else active_session.pack_id)
        plan_emoji = ((_pack.emoji or "").strip() + " ") if _pack and getattr(_pack, "emoji", None) else ""
        plan_safe = _escape_markdown(f"{plan_emoji}{plan_name}".strip())
        remaining = max(0, (active_session.takes_limit or 0) - (active_session.takes_used or 0))
        total = max(0, active_session.takes_limit or 0)
        has_remaining = remaining > 0
        is_trial_profile = pack_id_norm in {"free_preview", "trial"}
        is_paid_active = not is_trial_profile
        if is_trial_profile:
            trial_stats = TrialV2Service(db).get_trial_status(user.id) if bool(getattr(user, "trial_v2_eligible", False)) else None
            trial_total = int((trial_stats or {}).get("trend_slots_total", 3))
            trial_used = int((trial_stats or {}).get("trend_slots_used", 0))
            trial_remaining = max(0, trial_total - trial_used)
            text += (
                "Ваш текущий тариф: 🎬 Trial\n"
                f"У Вас осталось фото: {trial_remaining} из {trial_total}\n\n"
                "Что доступно:\n"
                "- 3 образа для пробы\n"
                "- 1 кнопка «Не подошло» на каждый выбранный образ\n"
                "- 1 выбранное фото можно открыть в полном качестве\n\n"
                "Как получить фото в полном качестве:\n"
                "- открыть сразу как только понравилось после оплаты через ЮМани\n"
                "или\n"
                "- бесплатно, если 1 приглашенный друг завершит свою первую генерацию"
            )
        else:
            text += (
                f"Тариф: {plan_safe}\n"
                f"У вас есть: {remaining} из {total} фото"
            )
    else:
        text += "Тариф: —\n\nКупите пакет, чтобы начать."
    return text, _profile_keyboard(is_paid_active=is_paid_active, has_remaining=has_remaining, is_trial_profile=is_trial_profile), is_paid_active


@profile_router.message(lambda m: (m.text or "").strip() == t("menu.btn.profile", "👤 Мой профиль"))
async def my_profile(message: Message):
    """Показать пакет, остаток фото и кнопки (В меню, Купить пакет, Пригласить, Оплата, Поддержка)."""
    telegram_id = str(message.from_user.id)
    try:
        with get_db_session() as db:
            user_service = UserService(db)
            session_svc = SessionService(db)
            user = user_service.get_by_telegram_id(telegram_id)
            if not user:
                user = user_service.get_or_create_user(
                    telegram_id,
                    telegram_username=message.from_user.username,
                    telegram_first_name=message.from_user.first_name,
                    telegram_last_name=message.from_user.last_name,
                )
            active_session = session_svc.get_active_session(user.id)
            text, profile_kb, is_paid_active = _build_profile_view(db, user, active_session)
            try:
                ProductAnalyticsService(db).track("button_click", user.id, properties={"button_id": "menu_profile"})
            except Exception:
                logger.exception("button_click track failed menu_profile")
        await message.answer(text, parse_mode="Markdown", reply_markup=profile_kb)
        if is_paid_active:
            await message.answer("👇 Главное меню", reply_markup=main_menu_keyboard())
    except Exception:
        logger.exception("Error in my_profile")
        await message.answer(t("errors.profile_load", "Ошибка загрузки профиля."), reply_markup=main_menu_keyboard())


# --- Referral program screens ---

@profile_router.callback_query(F.data == "referral:invite")
async def referral_invite(callback: CallbackQuery):
    """Show Trial V2 referral unlock screen."""
    telegram_id = str(callback.from_user.id)
    try:
        with get_db_session() as db:
            user_service = UserService(db)
            audit = AuditService(db)
            user = user_service.get_by_telegram_id(telegram_id)
            if not user:
                await callback.answer("Пользователь не найден.", show_alert=True)
                return

            ref_svc = ReferralService(db)
            code = ref_svc.get_or_create_code(user)

            audit.log(
                actor_type="user",
                actor_id=telegram_id,
                action="referral_invite_view",
                entity_type="user",
                entity_id=user.id,
                payload={"code": code},
            )

        text = (
            "🎁 *Получить бесплатно за друга*\n\n"
            "Пригласите 1 друга и получите 1 фото в полном качестве бесплатно.\n\n"
            "Условие: друг должен завершить первую генерацию (получить 3 превью)."
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Получить свою ссылку", callback_data="trial_ref:get_link")],
            [InlineKeyboardButton(text="✅ Проверить статус", callback_data="trial_ref:status")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="referral:back_profile")],
        ])
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
        await callback.answer()
    except Exception:
        logger.exception("Error in referral_invite")
        await callback.answer("Ошибка. Попробуйте позже.", show_alert=True)


@profile_router.callback_query(F.data.startswith("referral:copy:"))
async def referral_copy_link(callback: CallbackQuery):
    """User tapped copy — send link as a separate message for easy copying."""
    telegram_id = str(callback.from_user.id)
    code = callback.data.split(":")[-1]
    bot_username = settings.telegram_bot_username
    link = f"https://t.me/{bot_username}?start=ref_{code}" if bot_username else f"ref_{code}"

    try:
        with get_db_session() as db:
            audit = AuditService(db)
            audit.log(
                actor_type="user",
                actor_id=telegram_id,
                action="referral_link_created",
                entity_type="user",
                entity_id=telegram_id,
                payload={"code": code},
            )
    except Exception:
        pass

    await callback.message.answer(link)
    await callback.answer("Ссылка отправлена — перешлите или скопируйте!")


@profile_router.callback_query(F.data == "referral:status")
async def referral_status(callback: CallbackQuery):
    """Show Trial V2 referral unlock status."""
    telegram_id = str(callback.from_user.id)
    try:
        with get_db_session() as db:
            user_service = UserService(db)
            user = user_service.get_by_telegram_id(telegram_id)
            if user:
                try:
                    ProductAnalyticsService(db).track("button_click", user.id, properties={"button_id": "referral_status"})
                except Exception:
                    logger.exception("button_click track failed referral_status")
            if not user:
                await callback.answer("Пользователь не найден.", show_alert=True)
                return

            stats = TrialV2Service(db).get_referral_unlock_stats(user.id)

        text = (
            "📊 *Referral Unlock (Trial V2)*\n\n"
            f"🎁 Доступно наград: {stats['reward_available']}\n"
            f"📌 В резерве: {stats['reward_reserved']}\n"
            f"✅ Начислено всего: {stats['reward_earned_total']}/10\n"
            f"🧾 Забрано: {stats['reward_claimed_total']}\n"
            f"🗂 В очереди выбранных фото: {stats['pending_selections']}\n\n"
            "1 друг = 1 фото в полном качестве."
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Забрать фото", callback_data="trial_claim:next")],
            [InlineKeyboardButton(text="💌 Пригласить ещё", callback_data="trial_ref:get_link")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="referral:back_profile")],
        ])

        try:
            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
        except Exception:
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)
        await callback.answer()
    except Exception:
        logger.exception("Error in referral_status")
        await callback.answer("Ошибка. Попробуйте позже.", show_alert=True)


@profile_router.callback_query(F.data == "referral:back_profile")
async def referral_back_to_profile(callback: CallbackQuery):
    """Return to profile from referral screen (cannot mutate Message.from_user — Pydantic frozen)."""
    telegram_id = str(callback.from_user.id)
    try:
        with get_db_session() as db:
            user = UserService(db).get_by_telegram_id(telegram_id)
            if user:
                try:
                    ProductAnalyticsService(db).track("button_click", user.id, properties={"button_id": "referral_back_profile"})
                except Exception:
                    logger.exception("button_click track failed referral_back_profile")
        try:
            await callback.message.delete()
        except Exception:
            pass
        telegram_id = str(callback.from_user.id)
        with get_db_session() as db:
            user_service = UserService(db)
            session_svc = SessionService(db)
            user = user_service.get_by_telegram_id(telegram_id)
            if not user:
                user = user_service.get_or_create_user(
                    telegram_id,
                    telegram_username=callback.from_user.username,
                    telegram_first_name=callback.from_user.first_name,
                    telegram_last_name=callback.from_user.last_name,
                )
            active_session = session_svc.get_active_session(user.id)
            text, profile_kb, is_paid_active = _build_profile_view(db, user, active_session)
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=profile_kb)
        if is_paid_active:
            await callback.message.answer("👇 Главное меню", reply_markup=main_menu_keyboard())
    except Exception:
        logger.exception("Error in referral_back_to_profile")
        await callback.message.answer(t("errors.profile_load", "Ошибка загрузки профиля."), reply_markup=main_menu_keyboard())
    await callback.answer()
