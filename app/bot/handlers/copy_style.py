import asyncio
import logging
import os
from aiogram import Router, F, Bot
from aiogram.types import Message, FSInputFile
from aiogram.fsm.context import FSMContext
from app.bot.states import BotStates
from app.bot.helpers import t, tr, get_db_session, _document_image_ext, _try_delete_messages, logger
from app.bot.keyboards import main_menu_keyboard
from app.bot.constants import COPY_STYLE_INTRO_IMAGE_PATH, TREND_CUSTOM_ID, DEFAULT_ASPECT_RATIO
from app.core.config import settings
from app.services.users.service import UserService
from app.services.audit.service import AuditService
from app.services.product_analytics.service import ProductAnalyticsService
from app.utils.telegram_photo import path_for_telegram_photo
from app.bot.handlers.generation import _create_job_and_start_generation

copy_style_router = Router()


# --- "Сделать такую же" flow ---
@copy_style_router.message(lambda m: (m.text or "").strip() == t("menu.btn.copy_style", "🔄 Сделать такую же"))
async def start_copy_flow(message: Message, state: FSMContext, bot: Bot):
    """Начало флоу копирования стиля 1:1. Пост с картинкой, как в логе трендов."""
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
                ProductAnalyticsService(db).track("button_click", user.id, properties={"button_id": "menu_copy_style"})
        except Exception:
            logger.exception("button_click track failed menu_copy_style")
    copy_intro_text = t(
        "copy.start_text",
        "🔄 *Сделать такую же*\n\n"
        "Я могу скопировать 1:1 любой тренд.\n\n"
        "Загрузите картинку-образец в хорошем качестве — "
        "я изучу дизайн и подскажу, как сделать такую же.\n\n"
        "Поддерживаются: JPG, PNG, WEBP.",
    )
    try:
        await state.clear()
        await state.set_state(BotStates.waiting_for_reference_photo)
        photo_sent = False
        if os.path.isfile(COPY_STYLE_INTRO_IMAGE_PATH):
            photo_path, is_temp = path_for_telegram_photo(COPY_STYLE_INTRO_IMAGE_PATH)
            try:
                sent = await message.answer_photo(
                    FSInputFile(photo_path),
                    caption=copy_intro_text,
                    parse_mode="Markdown",
                    reply_markup=main_menu_keyboard(),
                )
                photo_sent = True
            except Exception as e:
                logger.warning("start_copy_flow_photo_failed", extra={"path": COPY_STYLE_INTRO_IMAGE_PATH, "error": str(e)})
            finally:
                if is_temp and photo_path and os.path.isfile(photo_path):
                    try:
                        os.unlink(photo_path)
                    except OSError:
                        pass
        if not photo_sent:
            sent = await message.answer(
                copy_intro_text,
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard(),
            )
        await state.update_data(last_bot_message_id=sent.message_id)
    except Exception:
        logger.exception("Error in start_copy_flow")
        await message.answer(t("errors.try_later", "Произошла ошибка. Попробуйте позже."), reply_markup=main_menu_keyboard())


@copy_style_router.message(BotStates.waiting_for_reference_photo, F.photo)
async def handle_reference_photo(message: Message, state: FSMContext, bot: Bot):
    """Принимаем референс, сохраняем путь, просим своё фото. Vision — после загрузки своего фото."""
    photo = message.photo[-1]
    try:
        inputs_dir = os.path.join(settings.storage_base_path, "inputs")
        os.makedirs(inputs_dir, exist_ok=True)
        local_path = os.path.join(inputs_dir, f"ref_{photo.file_id}.jpg")
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
    except Exception:
        logger.exception("Failed to save reference photo")
        await message.answer(t("flow.save_photo_error", "Не удалось сохранить фото. Попробуйте ещё раз."))
        return

    data = await state.get_data()
    await _try_delete_messages(bot, message.chat.id, data.get("last_bot_message_id"), message.message_id)
    await state.update_data(reference_path=local_path)
    await state.set_state(BotStates.waiting_for_self_photo)
    sent = await message.answer(
        "✅ Референс сохранён.\n\nОтправьте своё фото — по нему сохраним лицо и перенесём в сцену из образца.",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )
    await state.update_data(last_bot_message_id=sent.message_id)


@copy_style_router.message(BotStates.waiting_for_reference_photo, F.document)
async def handle_reference_photo_as_document(message: Message, state: FSMContext, bot: Bot):
    """Принимаем референс как документ, сохраняем путь, просим своё фото."""
    doc = message.document
    if not doc:
        await message.answer(t("errors.try_later_short", "Ошибка. Попробуйте позже."))
        return
    ext = _document_image_ext(doc.mime_type, doc.file_name)
    if not ext:
        await message.answer(t("flow.only_images", "Поддерживаются только изображения: JPG, PNG, WEBP. Отправьте файл с фото."))
        return
    try:
        inputs_dir = os.path.join(settings.storage_base_path, "inputs")
        os.makedirs(inputs_dir, exist_ok=True)
        local_path = os.path.join(inputs_dir, f"ref_{doc.file_id}{ext}")
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
    except Exception:
        logger.exception("Failed to save reference photo (document)")
        await message.answer(t("flow.save_file_error", "Не удалось сохранить файл. Попробуйте ещё раз."))
        return

    data = await state.get_data()
    await _try_delete_messages(bot, message.chat.id, data.get("last_bot_message_id"), message.message_id)
    await state.update_data(reference_path=local_path)
    await state.set_state(BotStates.waiting_for_self_photo)
    sent = await message.answer(
        "✅ Референс сохранён.\n\nОтправьте своё фото — по нему сохраним лицо и перенесём в сцену из образца.",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )
    await state.update_data(last_bot_message_id=sent.message_id)


@copy_style_router.message(BotStates.waiting_for_self_photo, F.photo)
async def handle_self_photo_for_copy(message: Message, state: FSMContext, bot: Bot):
    """Принимаем своё фото (identity), запускаем Vision с референсом + identity, переходим к формату."""
    telegram_id = str(message.from_user.id)
    data = await state.get_data()
    reference_path = data.get("reference_path")
    if not reference_path or not os.path.exists(reference_path):
        await message.answer(t("flow.session_expired_copy", "Сессия истекла. Начните заново: «🔄 Сделать такую же»."))
        await state.clear()
        return

    photo = message.photo[-1]
    try:
        with get_db_session() as db:
            UserService(db).get_or_create_user(
                telegram_id,
                telegram_username=message.from_user.username,
                telegram_first_name=message.from_user.first_name,
                telegram_last_name=message.from_user.last_name,
            )
        inputs_dir = os.path.join(settings.storage_base_path, "inputs")
        os.makedirs(inputs_dir, exist_ok=True)
        local_path = os.path.join(inputs_dir, f"{photo.file_id}.jpg")
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
    except Exception:
        logger.exception("Failed to save self photo for copy")
        await message.answer(t("flow.save_photo_error", "Не удалось сохранить фото. Попробуйте ещё раз."))
        return

    await _try_delete_messages(bot, message.chat.id, data.get("last_bot_message_id"), message.message_id)
    analyzing_msg = await message.answer(t("flow.analyzing", "⏳ Анализирую дизайн..."))
    try:
        from app.services.llm.vision_analyzer import analyze_for_copy_style
        copy_prompt = await asyncio.to_thread(analyze_for_copy_style, reference_path, local_path)
    except Exception:
        logger.exception("Vision analysis failed (copy_style)")
        await analyzing_msg.edit_text(
            "Не удалось проанализировать фото. Попробуйте другое изображение в хорошем качестве."
        )
        return

    await analyzing_msg.delete()
    try:
        with get_db_session() as db:
            AuditService(db).log(
                actor_type="user",
                actor_id=telegram_id,
                action="copy_flow_reference_analyzed",
                entity_type="session",
                entity_id=None,
                payload={"prompt_len": len(copy_prompt)},
            )
    except Exception:
        pass

    await state.update_data(
        photo_file_id=photo.file_id,
        photo_local_path=local_path,
        selected_trend_id=TREND_CUSTOM_ID,
        custom_prompt=copy_prompt,
        copy_flow_origin=True,
    )
    data = await state.get_data()
    async def _answer_alert_copy(text: str, show_alert: bool = False) -> None:
        await message.answer(text, reply_markup=main_menu_keyboard())
    ok = await _create_job_and_start_generation(
        bot=bot,
        state=state,
        format_key=DEFAULT_ASPECT_RATIO,
        chat_id=message.chat.id,
        message_ids_to_delete=data.get("last_bot_message_id"),
        from_user=message.from_user,
        answer_alert=_answer_alert_copy,
        send_progress_to_chat_id=message.chat.id,
    )


@copy_style_router.message(BotStates.waiting_for_self_photo, F.document)
async def handle_self_photo_as_document_for_copy(message: Message, state: FSMContext, bot: Bot):
    """Принимаем своё фото (identity) как документ, запускаем Vision, переходим к формату."""
    doc = message.document
    if not doc:
        await message.answer(t("errors.try_later_short", "Ошибка. Попробуйте позже."))
        return
    ext = _document_image_ext(doc.mime_type, doc.file_name)
    if not ext:
        await message.answer(t("flow.only_images", "Поддерживаются только изображения: JPG, PNG, WEBP. Отправьте файл с фото."))
        return
    telegram_id = str(message.from_user.id)
    data = await state.get_data()
    reference_path = data.get("reference_path")
    if not reference_path or not os.path.exists(reference_path):
        await message.answer(t("flow.session_expired_copy", "Сессия истекла. Начните заново: «🔄 Сделать такую же»."))
        await state.clear()
        return

    try:
        with get_db_session() as db:
            UserService(db).get_or_create_user(
                telegram_id,
                telegram_username=message.from_user.username,
                telegram_first_name=message.from_user.first_name,
                telegram_last_name=message.from_user.last_name,
            )
        inputs_dir = os.path.join(settings.storage_base_path, "inputs")
        os.makedirs(inputs_dir, exist_ok=True)
        local_path = os.path.join(inputs_dir, f"{doc.file_id}{ext}")
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
    except Exception:
        logger.exception("Failed to save self photo for copy (document)")
        await message.answer(t("flow.save_file_error", "Не удалось сохранить файл. Попробуйте ещё раз."))
        return

    await _try_delete_messages(bot, message.chat.id, data.get("last_bot_message_id"), message.message_id)
    analyzing_msg = await message.answer(t("flow.analyzing", "⏳ Анализирую дизайн..."))
    try:
        from app.services.llm.vision_analyzer import analyze_for_copy_style
        copy_prompt = await asyncio.to_thread(analyze_for_copy_style, reference_path, local_path)
    except Exception:
        logger.exception("Vision analysis failed (copy_style document)")
        await analyzing_msg.edit_text(
            "Не удалось проанализировать фото. Попробуйте другое изображение в хорошем качестве."
        )
        return

    await analyzing_msg.delete()
    try:
        with get_db_session() as db:
            AuditService(db).log(
                actor_type="user",
                actor_id=telegram_id,
                action="copy_flow_reference_analyzed",
                entity_type="session",
                entity_id=None,
                payload={"prompt_len": len(copy_prompt)},
            )
    except Exception:
        pass

    await state.update_data(
        photo_file_id=doc.file_id,
        photo_local_path=local_path,
        selected_trend_id=TREND_CUSTOM_ID,
        custom_prompt=copy_prompt,
        copy_flow_origin=True,
    )
    data = await state.get_data()
    async def _answer_alert_copy_doc(text: str, show_alert: bool = False) -> None:
        await message.answer(text, reply_markup=main_menu_keyboard())
    ok = await _create_job_and_start_generation(
        bot=bot,
        state=state,
        format_key=DEFAULT_ASPECT_RATIO,
        chat_id=message.chat.id,
        message_ids_to_delete=data.get("last_bot_message_id"),
        from_user=message.from_user,
        answer_alert=_answer_alert_copy_doc,
        send_progress_to_chat_id=message.chat.id,
    )


@copy_style_router.message(BotStates.waiting_for_reference_photo)
async def copy_flow_wrong_input_ref(message: Message):
    await message.answer(t("flow.send_reference", "Отправьте картинку-образец (фото)."))


@copy_style_router.message(BotStates.waiting_for_self_photo)
async def copy_flow_wrong_input_self(message: Message):
    await message.answer(t("flow.send_your_photo", "Отправьте свою фотографию."))
