import logging
import os

from aiogram import Router, F, Bot
from aiogram.types import (
    Message, CallbackQuery, ErrorEvent, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile,
)
from aiogram.fsm.context import FSMContext

from app.bot.states import BotStates
from app.bot.helpers import t, tr, get_db_session, logger
from app.bot.keyboards import main_menu_keyboard, audience_keyboard, themes_keyboard, create_photo_only_keyboard
from app.bot.constants import (
    RULE_IMAGE_PATH, REQUEST_PHOTO_TEXT_DEFAULT, AUDIENCE_PROMPT_DEFAULT,
)
from app.core.config import settings
from app.services.users.service import UserService
from app.services.trends.service import TrendService
from app.services.themes.service import ThemeService
from app.services.sessions.service import SessionService
from app.services.jobs.service import JobService
from app.services.product_analytics.service import ProductAnalyticsService
from app.constants import AUDIENCE_WOMEN
from app.models.user import User
from app.utils.telegram_photo import path_for_telegram_photo

fallback_router = Router()


def _menu_keyboard_for_waiting_photo(data: dict) -> object:
    return create_photo_only_keyboard() if data.get("limited_menu_until_first_photo") else main_menu_keyboard()


@fallback_router.callback_query(
    F.data.in_({"error_action:menu", "error_action:retry", "success_action:menu", "success_action:more"})
)
async def handle_error_recovery(callback: CallbackQuery, state: FSMContext):
    """После генерации (успех или ошибка): вернуться в меню или сгенерировать ещё."""
    telegram_id = str(callback.from_user.id) if callback.from_user else None
    action = callback.data.split(":", 1)[-1]  # menu, retry или more
    button_id = "success_menu" if callback.data == "success_action:menu" else "success_more" if callback.data == "success_action:more" else "error_menu" if action == "menu" else "error_retry"
    if telegram_id:
        try:
            with get_db_session() as db:
                user = UserService(db).get_by_telegram_id(telegram_id)
                if user:
                    ProductAnalyticsService(db).track("button_click", user.id, properties={"button_id": button_id})
        except Exception:
            logger.exception("button_click track failed handle_error_recovery")
    await state.clear()
    if action == "menu":
        await callback.message.answer(
            t("action.choose", "Выберите действие:"),
            reply_markup=main_menu_keyboard(),
        )
    else:
        # retry / more — главное меню с подсказкой
        await callback.message.answer(
            t("action.create_again", "Чтобы создать изображение заново, нажмите «🔥 Создать фото» и выберите тренд."),
            reply_markup=main_menu_keyboard(),
        )
    await callback.answer()


@fallback_router.callback_query(F.data == "error_action:replace_photo")
async def error_replace_photo(callback: CallbackQuery, state: FSMContext):
    """После ошибки: перейти к шагу загрузки нового исходного фото."""
    await state.clear()
    await state.set_state(BotStates.waiting_for_photo)
    request_text = t("flow.request_photo", REQUEST_PHOTO_TEXT_DEFAULT)
    if os.path.exists(RULE_IMAGE_PATH):
        try:
            photo_path, is_temp = path_for_telegram_photo(RULE_IMAGE_PATH)
            sent = await callback.message.answer_photo(
                photo=FSInputFile(photo_path),
                caption=request_text,
                parse_mode="HTML",
                reply_markup=main_menu_keyboard(),
            )
            if is_temp and os.path.isfile(photo_path):
                try:
                    os.unlink(photo_path)
                except OSError:
                    pass
        except Exception as e:
            logger.warning("rule_photo_failed", extra={"path": RULE_IMAGE_PATH, "error": str(e)})
            sent = await callback.message.answer(request_text, parse_mode="HTML", reply_markup=main_menu_keyboard())
    else:
        sent = await callback.message.answer(request_text, parse_mode="HTML", reply_markup=main_menu_keyboard())
    await state.update_data(last_bot_message_id=sent.message_id)
    await callback.answer()


@fallback_router.callback_query(F.data.startswith("error_action:choose_trend:"))
async def error_choose_trend(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """После ошибки: выбрать другой тренд на том же исходном фото (если доступно)."""
    telegram_id = str(callback.from_user.id)
    failed_job_id = callback.data.split(":", 2)[-1].strip()
    if not failed_job_id:
        await callback.answer(t("errors.job_not_found", "Кадр не найден."), show_alert=True)
        return

    try:
        data = await state.get_data()
        audience = (data.get("audience_type") or "").strip().lower() or AUDIENCE_WOMEN
        with get_db_session() as db:
            job_service = JobService(db)
            trend_service = TrendService(db)
            user = db.query(User).filter(User.telegram_id == telegram_id).first()
            job = job_service.get(failed_job_id)
            if not user or not job or str(job.user_id) != str(user.id):
                await callback.answer(t("errors.job_not_found", "Кадр не найден."), show_alert=True)
                return
            try:
                ProductAnalyticsService(db).track(
                    "button_click",
                    user.id,
                    properties={"button_id": "error_choose_trend", "job_id": failed_job_id},
                )
            except Exception:
                logger.exception("button_click track failed error_choose_trend")

            file_ids = list(job.input_file_ids or [])
            if "ref" in file_ids:
                await callback.answer(t("errors.choose_new_photo", "Для этого сценария выберите новое фото."), show_alert=True)
                return
            if not file_ids:
                await callback.answer(t("errors.no_source_photo", "Нет исходного фото. Загрузите новое."), show_alert=True)
                return

            photo_file_id = file_ids[0]
            theme_service = ThemeService(db)
            theme_ids_with_trends = trend_service.list_theme_ids_with_active_trends(audience)
            all_themes = theme_service.list_all()
            themes = [t for t in all_themes if t.enabled and t.id in theme_ids_with_trends]
            themes_data = [{"id": t.id, "name": t.name, "emoji": t.emoji or ""} for t in themes]

        # Скачиваем исходное фото по file_id заново в локальное хранилище
        file = await bot.get_file(photo_file_id)
        ext = (os.path.splitext(file.file_path or "")[1] or ".jpg").lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            ext = ".jpg"
        inputs_dir = os.path.join(settings.storage_base_path, "inputs")
        os.makedirs(inputs_dir, exist_ok=True)
        local_path = os.path.join(inputs_dir, f"retry_trend_{failed_job_id}_{photo_file_id[:16]}{ext}")
        await bot.download_file(file.file_path, local_path)
        size_mb = os.path.getsize(local_path) / (1024 * 1024)
        if size_mb > settings.max_file_size_mb:
            try:
                os.remove(local_path)
            except OSError:
                pass
            await callback.answer(
                tr("errors.file_too_large", "Файл слишком большой ({size_mb:.1f} МБ). Загрузите другое фото.", size_mb=size_mb),
                show_alert=True,
            )
            return

        await state.clear()
        await state.update_data(
            photo_file_id=photo_file_id,
            photo_local_path=local_path,
            selected_trend_id=None,
            selected_trend_name=None,
            custom_prompt=None,
            audience_type=audience,
        )
        await state.set_state(BotStates.waiting_for_trend)
        sent = await callback.message.answer(
            t("flow.choose_other_trend", "Выберите тематику и другой тренд для этого же фото:"),
            reply_markup=themes_keyboard(themes_data),
        )
        await state.update_data(last_bot_message_id=sent.message_id)
        await callback.answer()
    except Exception:
        logger.exception("Error in error_choose_trend", extra={"user_id": telegram_id, "job_id": failed_job_id})
        await callback.answer(t("errors.try_again_alert", "Ошибка. Попробуйте снова."), show_alert=True)


@fallback_router.message()
async def unknown_message(message: Message, state: FSMContext):
    """Handle unknown messages (wrong content type in current state)."""
    if (getattr(message.chat, "type", None) or "") != "private":
        return
    current = await state.get_state()
    data = await state.get_data()
    if current == BotStates.waiting_for_audience:
        await message.answer(t("audience.prompt", AUDIENCE_PROMPT_DEFAULT), reply_markup=audience_keyboard())
    elif current == BotStates.waiting_for_photo:
        await message.answer(
            t("nav.upload_photo_or_btn", "Отправьте фото или нажмите «🔥 Создать фото»."),
            reply_markup=_menu_keyboard_for_waiting_photo(data),
        )
    elif current == BotStates.waiting_for_trend:
        await message.answer("Выберите тематику и тренд по кнопкам выше.")
    elif current == BotStates.waiting_for_format:
        await message.answer("Нажмите «Далее» для генерации или «Назад к трендам».")
    elif current == BotStates.waiting_for_reference_photo:
        await message.answer(t("flow.send_reference", "Отправьте картинку-образец для копирования стиля."))
    elif current == BotStates.waiting_for_self_photo:
        await message.answer(t("flow.send_your_photo", "Отправьте свою фотографию."))
    elif current == BotStates.waiting_for_prompt:
        await message.answer(t("flow.enter_idea", "Введите текстом описание своей идеи (или выберите тренд по кнопкам)."))
    elif current == BotStates.bank_transfer_waiting_receipt:
        await state.clear()
        await message.answer(
            "Оплата переводом отключена. Откройте магазин и оплатите через ЮMoney.",
            reply_markup=main_menu_keyboard(),
        )
    elif current in (
        BotStates.merge_waiting_count,
        BotStates.merge_waiting_photo_1,
        BotStates.merge_waiting_photo_2,
        BotStates.merge_waiting_photo_3,
    ):
        await message.answer(
            "🧩 Вы в режиме склейки фото. Отправьте фото или нажмите «🧩 Соединить фото» снова.",
            reply_markup=main_menu_keyboard(),
        )
    else:
        await message.answer(
            t("nav.main_hint", "Нажмите «🔥 Создать фото» или «🔄 Сделать такую же» — или /help для справки."),
            reply_markup=main_menu_keyboard(),
        )


async def on_error(event: ErrorEvent, *args, **kwargs):
    """Global error handler."""
    logger.exception(
        "Error in handler",
        extra={"error": str(event.exception)},
    )
