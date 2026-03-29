"""Handlers for theme/trend selection, navigation, profile and support."""
import logging
import os
from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from app.bot.states import BotStates
from app.bot.helpers import (
    t, tr, get_db_session, _resolve_trend_example_path, _try_delete_messages, logger,
)
from app.bot.handlers.profile import _build_profile_view
from app.bot.keyboards import (
    main_menu_keyboard, themes_keyboard, trends_in_theme_keyboard, format_keyboard,
)
from app.bot.constants import (
    THEME_CB_PREFIX, NAV_THEMES, TREND_CUSTOM_ID, TRENDS_PER_PAGE,
    DEFAULT_ASPECT_RATIO, PHOTO_ACCEPTED_CAPTION_DEFAULT,
)
from app.core.config import settings
from app.constants import AUDIENCE_WOMEN, audience_in_target_audiences
from app.services.users.service import UserService
from app.services.themes.service import ThemeService
from app.services.trends.service import TrendService
from app.services.sessions.service import SessionService
from app.services.audit.service import AuditService
from app.services.product_analytics.service import ProductAnalyticsService
from app.models.user import User
from app.utils.telegram_photo import path_for_telegram_photo
from app.bot.handlers.generation import _create_job_and_start_generation

themes_router = Router()


# --- Step 2a: Theme selected → show first page of trends; or theme page (‹ 1 2 3 ›) ---
def _parse_theme_callback(data: str) -> tuple[str | None, int | None]:
    """Parse theme:uuid or theme:uuid:page. Returns (theme_id, page) where page is 0-based or None for first page."""
    if not data.startswith(THEME_CB_PREFIX):
        return None, None
    rest = data[len(THEME_CB_PREFIX):].strip()
    if ":" in rest:
        parts = rest.split(":", 1)
        theme_id = parts[0].strip()
        try:
            page = int(parts[1].strip())
            return theme_id if theme_id else None, max(0, page)
        except (ValueError, IndexError):
            return theme_id if theme_id else None, 0
    return rest if rest else None, 0


@themes_router.callback_query(F.data.startswith(THEME_CB_PREFIX))
async def select_theme_or_theme_page(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Открыть тематику (первая страница трендов) или переключить страницу (‹ 1 2 3 ›)."""
    theme_id, page = _parse_theme_callback(callback.data)
    if not theme_id:
        await callback.answer(t("errors.try_again", "Ошибка. Попробуйте ещё раз."), show_alert=True)
        return
    data = await state.get_data()
    if not data.get("photo_file_id"):
        await callback.answer(t("errors.send_photo_first", "Сначала отправьте фото."), show_alert=True)
        return
    try:
        with get_db_session() as db:
            theme_service = ThemeService(db)
            trend_service = TrendService(db)
            theme = theme_service.get(theme_id)
            if not theme or not theme.enabled:
                await callback.answer(t("errors.trend_unavailable", "Тематика недоступна."), show_alert=True)
                return
            audience = (data.get("audience_type") or "").strip().lower() or AUDIENCE_WOMEN
            trends = trend_service.list_active_by_theme(theme_id, audience)
            if not trends:
                await callback.answer(t("errors.no_trends_short", "Нет трендов в этой тематике."), show_alert=True)
                return
            theme_name_display = f"{theme.emoji or ''} {theme.name}".strip()
            total_pages = (len(trends) + TRENDS_PER_PAGE - 1) // TRENDS_PER_PAGE
            page = min(max(0, page), total_pages - 1) if total_pages else 0
            start = page * TRENDS_PER_PAGE
            trends_page = trends[start : start + TRENDS_PER_PAGE]
            trends_data = [{"id": t.id, "name": t.name, "emoji": t.emoji or ""} for t in trends_page]
        caption = tr(
            "flow.theme_page_caption",
            "Тематика: {theme_name} — стр. {current} из {total}",
            theme_name=theme_name_display,
            current=page + 1,
            total=total_pages,
        )
        kb = trends_in_theme_keyboard(theme_id, trends_data, page, total_pages)
        current_theme_id = data.get("current_theme_id")
        opening_from_list = current_theme_id is None or current_theme_id != theme_id
        if opening_from_list:
            try:
                await callback.message.delete()
            except Exception:
                pass
            sent = await callback.message.answer(caption, reply_markup=kb)
            await state.update_data(
                current_theme_id=theme_id,
                current_theme_page=page,
                last_bot_message_id=sent.message_id,
                last_instruction_message_id=None,
            )
        else:
            try:
                await callback.message.edit_text(caption, reply_markup=kb)
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e):
                    raise
            await state.update_data(current_theme_page=page)
        telegram_id = str(callback.from_user.id) if callback.from_user else None
        if telegram_id:
            try:
                with get_db_session() as db2:
                    user = UserService(db2).get_by_telegram_id(telegram_id)
                    if user:
                        ProductAnalyticsService(db2).track(
                            "theme_selected",
                            user.id,
                            properties={"button_id": "theme_selected", "theme_id": theme_id, "page": page},
                        )
            except Exception:
                logger.exception("theme_selected track failed")
        await callback.answer()
    except Exception as e:
        logger.exception("Error in select_theme_or_theme_page: %s", e)
        await callback.answer(t("errors.try_later_short", "Ошибка. Попробуйте позже."), show_alert=True)


@themes_router.callback_query(F.data == NAV_THEMES)
async def nav_back_to_themes(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Назад к списку тематик (фото остаётся в состоянии)."""
    data = await state.get_data()
    if not data.get("photo_file_id") or not data.get("photo_local_path"):
        await callback.answer(t("errors.session_expired_photo", "Сессия истекла. Отправьте фото заново."), show_alert=True)
        await state.clear()
        await callback.message.answer(t("flow.start_over", "Начните заново:"), reply_markup=main_menu_keyboard())
        return
    try:
        audience = (data.get("audience_type") or "").strip().lower() or AUDIENCE_WOMEN
        with get_db_session() as db:
            theme_service = ThemeService(db)
            trend_service = TrendService(db)
            theme_ids_with_trends = trend_service.list_theme_ids_with_active_trends(audience)
            all_themes = theme_service.list_all()
            themes = [t for t in all_themes if t.enabled and t.id in theme_ids_with_trends]
            themes_data = [{"id": t.id, "name": t.name, "emoji": t.emoji or ""} for t in themes]
        await state.update_data(
            current_theme_id=None,
            current_theme_page=None,
            selected_trend_id=None,
            selected_trend_name=None,
        )
        caption = t("flow.photo_accepted_choose_theme", PHOTO_ACCEPTED_CAPTION_DEFAULT)
        telegram_id = str(callback.from_user.id) if callback.from_user else None
        if telegram_id:
            try:
                with get_db_session() as db:
                    user = UserService(db).get_by_telegram_id(telegram_id)
                    if user:
                        ProductAnalyticsService(db).track("button_click", user.id, properties={"button_id": "nav_themes"})
            except Exception:
                logger.exception("button_click track failed nav_themes")
        await callback.message.edit_text(caption, reply_markup=themes_keyboard(themes_data))
        await callback.answer()
    except Exception as e:
        logger.exception("Error in nav_back_to_themes: %s", e)
        await callback.answer(t("errors.try_later_short", "Ошибка. Попробуйте позже."), show_alert=True)


# --- Step 2: Trend selected or "Своя идея" ---
@themes_router.callback_query(F.data.startswith("trend:"))
async def select_trend_or_idea(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Handle trend or 'Своя идея' selection."""
    telegram_id = str(callback.from_user.id)
    trend_id = callback.data.split(":", 1)[1]
    
    data = await state.get_data()
    if not data.get("photo_file_id"):
        await callback.answer(t("errors.send_photo_first", "Сначала отправьте фото."), show_alert=True)
        return
    
    await _try_delete_messages(bot, callback.message.chat.id, data.get("last_bot_message_id"), callback.message.message_id)
    
    if trend_id == TREND_CUSTOM_ID:
        await state.update_data(selected_trend_id=TREND_CUSTOM_ID)
        await state.set_state(BotStates.waiting_for_prompt)
        sent = await callback.message.answer(
            "💡 Своя идея\n\n"
            "Опишите, как вы хотите обработать фото. Например:\n"
            "«Сделай в стиле аниме» или «Добавь закат на фон»",
            reply_markup=main_menu_keyboard(),
        )
        await state.update_data(last_bot_message_id=sent.message_id)
        await callback.answer()
        return
    
    try:
        audience = (data.get("audience_type") or "").strip().lower() or AUDIENCE_WOMEN
        trend_name = ""
        trend_emoji = ""
        example_path = None
        with get_db_session() as db:
            trend_service = TrendService(db)
            audit = AuditService(db)

            trend = trend_service.get(trend_id)
            if not trend or not trend.enabled:
                await callback.answer(t("errors.trend_unavailable", "Тренд недоступен"), show_alert=True)
                return
            if not audience_in_target_audiences(audience, getattr(trend, "target_audiences", None)):
                await callback.answer(t("audience.trend_unavailable_audience", "Тренд недоступен для выбранной ЦА."), show_alert=True)
                return
            trend_name = trend.name
            trend_emoji = trend.emoji
            example_path = _resolve_trend_example_path(getattr(trend, "example_image_path", None), str(trend.id))
            await state.update_data(selected_trend_id=trend_id, selected_trend_name=trend_name)

            audit.log(
                actor_type="user",
                actor_id=telegram_id,
                action="trend_selected",
                entity_type="trend",
                entity_id=trend_id,
                payload={},
            )
            user = UserService(db).get_by_telegram_id(telegram_id)
            if user:
                ProductAnalyticsService(db).track("trend_viewed", user.id, trend_id=trend_id)

        nav_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="➡️ Далее", callback_data=f"format:{DEFAULT_ASPECT_RATIO}")],
                [InlineKeyboardButton(text=t("nav.btn.back_to_trends", "⬅️ Назад к трендам"), callback_data="nav:trends")],
            ]
        )
        preview_caption = (
            f"{trend_emoji or '🎬'} Тренд: {trend_name}\n\n"
            "Посмотрите превью и нажмите «Далее» для генерации."
        )
        if example_path and os.path.isfile(example_path):
            photo_path, is_temp = path_for_telegram_photo(example_path)
            try:
                sent = await callback.message.answer_photo(
                    photo=FSInputFile(photo_path),
                    caption=preview_caption,
                    reply_markup=nav_kb,
                )
                await state.set_state(BotStates.waiting_for_format)
                await state.update_data(last_bot_message_id=sent.message_id)
            finally:
                if is_temp and os.path.isfile(photo_path):
                    try:
                        os.unlink(photo_path)
                    except OSError:
                        pass
        else:
            sent = await callback.message.answer(
                preview_caption + "\n\n⚠️ Превью временно недоступно, но можно продолжить.",
                reply_markup=nav_kb,
            )
            await state.set_state(BotStates.waiting_for_format)
            await state.update_data(last_bot_message_id=sent.message_id)
        await callback.answer()
    except Exception:
        logger.exception("Error in select_trend_or_idea")
        await callback.answer(t("errors.try_later_short", "Ошибка. Попробуйте позже."), show_alert=True)


# --- Step 2b: Custom prompt (for "Своя идея") ---
@themes_router.message(BotStates.waiting_for_prompt, F.text)
async def handle_custom_prompt(message: Message, state: FSMContext, bot: Bot):
    """Receive user's custom prompt for 'Своя идея'."""
    prompt = (message.text or "").strip()
    if len(prompt) < 3:
        await message.answer(t("errors.idea_min_length", "Опишите идею подробнее (минимум 3 символа)."))
        return
    if len(prompt) > 2000:
        await message.answer(t("errors.idea_max_length", "Текст слишком длинный. Сократите до 2000 символов."))
        return
    telegram_id = str(message.from_user.id) if message.from_user else None
    if telegram_id:
        try:
            with get_db_session() as db:
                user = UserService(db).get_by_telegram_id(telegram_id)
                if user:
                    ProductAnalyticsService(db).track(
                        "custom_prompt_submitted",
                        user.id,
                        properties={"button_id": "custom_prompt_submitted", "length": len(prompt)},
                    )
        except Exception:
            logger.exception("custom_prompt_submitted track failed")
    data = await state.get_data()
    await state.update_data(custom_prompt=prompt)

    async def _answer_alert_prompt(text: str, show_alert: bool = False) -> None:
        await message.answer(text, reply_markup=main_menu_keyboard())

    ok = await _create_job_and_start_generation(
        bot=bot,
        state=state,
        format_key=DEFAULT_ASPECT_RATIO,
        chat_id=message.chat.id,
        message_ids_to_delete=data.get("last_bot_message_id"),
        from_user=message.from_user,
        answer_alert=_answer_alert_prompt,
        send_progress_to_chat_id=message.chat.id,
    )


# --- Назад к трендам / В меню (с экрана выбора формата) ---
@themes_router.callback_query(F.data == "nav:trends")
async def nav_back_to_trends(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Вернуться к выбору тренда: если есть current_theme_id — страница трендов темы, иначе — список тематик."""
    data = await state.get_data()
    if not data.get("photo_file_id") or not data.get("photo_local_path"):
        await callback.answer(t("errors.session_expired_photo", "Сессия истекла. Отправьте фото заново."), show_alert=True)
        await state.clear()
        await callback.message.answer(t("flow.start_over", "Начните заново:"), reply_markup=main_menu_keyboard())
        return
    try:
        audience = (data.get("audience_type") or "").strip().lower() or AUDIENCE_WOMEN
        await state.set_state(BotStates.waiting_for_trend)
        await state.update_data(selected_trend_id=None, selected_trend_name=None, custom_prompt=None)
        with get_db_session() as db:
            theme_service = ThemeService(db)
            trend_service = TrendService(db)
            current_theme_id = data.get("current_theme_id")
            if current_theme_id:
                theme = theme_service.get(current_theme_id)
                if theme and theme.enabled:
                    trends = trend_service.list_active_by_theme(current_theme_id, audience)
                    if trends:
                        page = max(0, min(data.get("current_theme_page", 0), (len(trends) - 1) // TRENDS_PER_PAGE))
                        total_pages = (len(trends) + TRENDS_PER_PAGE - 1) // TRENDS_PER_PAGE
                        start = page * TRENDS_PER_PAGE
                        trends_page = trends[start : start + TRENDS_PER_PAGE]
                        trends_data = [{"id": t.id, "name": t.name, "emoji": t.emoji or ""} for t in trends_page]
                        caption = tr(
                            "flow.theme_page_caption",
                            "Тематика: {theme_name} — стр. {current} из {total}",
                            theme_name=f"{theme.emoji or ''} {theme.name}".strip(),
                            current=page + 1,
                            total=total_pages,
                        )
                        await callback.message.answer(caption, reply_markup=trends_in_theme_keyboard(current_theme_id, trends_data, page, total_pages))
                        await state.update_data(current_theme_id=current_theme_id, current_theme_page=page)
                        await callback.answer()
                        return
            theme_ids_with_trends = trend_service.list_theme_ids_with_active_trends(audience)
            all_themes = theme_service.list_all()
            themes = [t for t in all_themes if t.enabled and t.id in theme_ids_with_trends]
            themes_data = [{"id": t.id, "name": t.name, "emoji": t.emoji or ""} for t in themes]
        caption = t("flow.photo_accepted_choose_theme", PHOTO_ACCEPTED_CAPTION_DEFAULT)
        telegram_id = str(callback.from_user.id) if callback.from_user else None
        if telegram_id:
            try:
                with get_db_session() as db:
                    user = UserService(db).get_by_telegram_id(telegram_id)
                    if user:
                        ProductAnalyticsService(db).track("button_click", user.id, properties={"button_id": "nav_trends"})
            except Exception:
                logger.exception("button_click track failed nav_trends")
        await callback.message.answer(
            caption,
            reply_markup=themes_keyboard(themes_data),
        )
        await callback.answer()
    except Exception:
        logger.exception("Error in nav_back_to_trends")
        await callback.answer(t("errors.try_later_short", "Ошибка. Попробуйте позже."), show_alert=True)


@themes_router.callback_query(F.data == "nav:menu")
async def nav_back_to_menu(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Вернуться в главное меню."""
    telegram_id = str(callback.from_user.id)
    try:
        with get_db_session() as db:
            user = UserService(db).get_by_telegram_id(telegram_id)
            if user:
                ProductAnalyticsService(db).track(
                    "button_click",
                    user.id,
                    properties={"button_id": "nav_menu"},
                )
    except Exception:
        logger.exception("button_click track failed nav_menu")
    await state.clear()
    await _try_delete_messages(bot, callback.message.chat.id, callback.message.message_id)
    await callback.message.answer(
        "Главное меню. Загрузите фото, чтобы начать.",
        reply_markup=main_menu_keyboard(),
    )
    await callback.answer()


@themes_router.callback_query(F.data == "nav:profile")
async def nav_profile(callback: CallbackQuery):
    """Открыть «Мой профиль» по кнопке после 4K или из меню."""
    telegram_id = str(callback.from_user.id)
    try:
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
            try:
                ProductAnalyticsService(db).track("button_click", user.id, properties={"button_id": "nav_profile"})
            except Exception:
                logger.exception("button_click track failed nav_profile")
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=profile_kb)
        if is_paid_active:
            await callback.message.answer("👇 Главное меню", reply_markup=main_menu_keyboard())
        await callback.answer()
    except Exception:
        logger.exception("Error in nav_profile")
        await callback.answer(t("errors.profile_load", "Ошибка загрузки профиля."), show_alert=True)


@themes_router.callback_query(F.data == "profile:payment")
async def profile_payment(callback: CallbackQuery):
    """Экран оплаты: открыть магазин и оплатить через ЮMoney."""
    telegram_id = str(callback.from_user.id) if callback.from_user else None
    if telegram_id:
        try:
            with get_db_session() as db:
                user = UserService(db).get_by_telegram_id(telegram_id)
                if user:
                    ProductAnalyticsService(db).track("button_click", user.id, properties={"button_id": "profile_payment"})
        except Exception:
            logger.exception("button_click track failed profile_payment")
    try:
        text = (
            "Пополнить баланс:\n\n"
            "• *Магазин* — выберите пакет\n"
            "• *ЮMoney* — оплата картой/кошельком в окне оплаты Telegram\n\n"
            "Выберите действие:"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Открыть магазин", callback_data="shop:open")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="nav:profile")],
        ])
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)
        await callback.answer()
    except Exception:
        logger.exception("Error in profile_payment")
        await callback.answer(t("errors.try_later", "Произошла ошибка. Попробуйте позже."), show_alert=True)


@themes_router.callback_query(F.data == "profile:support")
async def profile_support(callback: CallbackQuery):
    """Показать текст поддержки по платежам (как /paysupport)."""
    telegram_id = str(callback.from_user.id) if callback.from_user else None
    if telegram_id:
        try:
            with get_db_session() as db:
                user = UserService(db).get_by_telegram_id(telegram_id)
                if user:
                    ProductAnalyticsService(db).track("button_click", user.id, properties={"button_id": "profile_support"})
        except Exception:
            logger.exception("button_click track failed profile_support")
    try:
        await callback.message.answer(
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
        await callback.answer()
    except Exception:
        logger.exception("Error in profile_support")
        await callback.answer(t("errors.try_later", "Произошла ошибка. Попробуйте позже."), show_alert=True)


@themes_router.message(BotStates.waiting_for_prompt)
async def waiting_prompt_wrong_input(message: Message):
    """Non-text input while expecting a custom idea prompt."""
    await message.answer(t("flow.prompt_placeholder", "Опишите свою идею текстом. Например: «Сделай в стиле аниме»"))
