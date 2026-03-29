import logging
import os
from uuid import uuid4
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from app.bot.states import BotStates
from app.bot.helpers import t, get_db_session, _edit_message_text_or_caption, logger
from app.bot.keyboards import main_menu_keyboard
from app.bot.constants import MERGE_INTRO_IMAGE_PATH
from app.core.config import settings
from app.services.users.service import UserService
from app.services.audit.service import AuditService
from app.services.product_analytics.service import ProductAnalyticsService
from app.services.photo_merge.settings_service import PhotoMergeSettingsService
from app.models.photo_merge_job import PhotoMergeJob
from app.utils.telegram_photo import path_for_telegram_photo

merge_router = Router()


@merge_router.message(lambda m: (m.text or "").strip() == t("menu.btn.merge_photos", "🧩 Соединить фото"))
async def start_merge_flow(message: Message, state: FSMContext):
    """Пользователь нажал кнопку 'Соединить фото'. Отправляем интро с картинкой merge_2.png (ужатой при >10 МБ)."""
    telegram_id = str(message.from_user.id)
    try:
        with get_db_session() as db:
            user = UserService(db).get_or_create_user(
                telegram_id,
                telegram_username=message.from_user.username,
                telegram_first_name=message.from_user.first_name,
                telegram_last_name=message.from_user.last_name,
            )
            ProductAnalyticsService(db).track("button_click", user.id, properties={"button_id": "menu_merge_photos"})
    except Exception:
        logger.exception("button_click track failed menu_merge_photos")
    merge_intro_text = (
        "🧩 Соединить фото\n\n"
        "Используйте это, если у вас нет совместного фото\n"
        "и вы хотите создать парный образ в трендах\n\n"
        "Сервис объединяет два фото в одно\n"
        "и передаёт их в модель как единое изображение\n\n"
        "Мы рекомендуем этот способ —\n"
        "так модель точнее создаёт парные образы\n\n"
        "👇 Сколько фотографий хотите объединить?"
    )
    merge_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👤👤 2 фото", callback_data="merge_count:2"),
            InlineKeyboardButton(text="👤👤👤 3 фото", callback_data="merge_count:3"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="merge_cancel")],
    ])
    try:
        with get_db_session() as db:
            svc_settings = PhotoMergeSettingsService(db)
            cfg = svc_settings.as_dict()
        if not cfg["enabled"]:
            await message.answer("🔒 Сервис склейки фото временно недоступен.")
            return

        await state.clear()
        await state.set_state(BotStates.merge_waiting_count)
        photo_sent = False
        if os.path.isfile(MERGE_INTRO_IMAGE_PATH):
            photo_path, is_temp = path_for_telegram_photo(MERGE_INTRO_IMAGE_PATH)
            try:
                await message.answer_photo(
                    FSInputFile(photo_path),
                    caption=merge_intro_text,
                    parse_mode="HTML",
                    reply_markup=merge_keyboard,
                )
                photo_sent = True
            except Exception as e:
                logger.warning("start_merge_flow_photo_failed", extra={"path": MERGE_INTRO_IMAGE_PATH, "error": str(e)})
            finally:
                if is_temp and photo_path and os.path.isfile(photo_path):
                    try:
                        os.unlink(photo_path)
                    except OSError:
                        pass
        if not photo_sent:
            await message.answer(
                merge_intro_text,
                parse_mode="HTML",
                reply_markup=merge_keyboard,
            )
        with get_db_session() as db:
            AuditService(db).log(
                actor_type="user",
                actor_id=telegram_id,
                action="photo_merge_started",
                entity_type="user",
                entity_id=telegram_id,
            )
    except Exception:
        logger.exception("start_merge_flow error")
        await message.answer("Произошла ошибка. Попробуйте позже.")


@merge_router.callback_query(F.data.startswith("merge_count:"))
async def merge_count_selected(callback: CallbackQuery, state: FSMContext):
    count = int(callback.data.split(":")[1])
    telegram_id = str(callback.from_user.id)
    await state.update_data(merge_count=count, merge_photos_paths=[])
    await state.set_state(BotStates.merge_waiting_photo_1)
    next_text = (
        f"🧩 <b>Соединить фото</b> — {count} фото\n\n"
        "📷 Отправьте фото 1 из " + str(count) + " (можно как фото или как документ)."
    )
    await _edit_message_text_or_caption(callback.message, next_text)
    await callback.answer()
    try:
        with get_db_session() as db:
            AuditService(db).log(
                actor_type="user",
                actor_id=telegram_id,
                action="photo_merge_count_selected",
                entity_type="user",
                entity_id=telegram_id,
                payload={"count": count},
            )
    except Exception:
        logger.exception("merge_count_selected audit error")


@merge_router.callback_query(F.data == "merge_cancel")
async def merge_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await _edit_message_text_or_caption(callback.message, "Отменено.", reply_markup=None)
    except Exception as e:
        logger.warning("merge_cancel edit failed (message may be media)", extra={"error": str(e)})
    await callback.answer()
    await callback.message.answer("Выберите действие:", reply_markup=main_menu_keyboard())


async def _download_merge_photo(message: Message, bot: Bot, cfg: dict) -> str | None:
    """Скачать фото из сообщения, вернуть путь или None при ошибке."""
    max_bytes = cfg["max_input_file_mb"] * 1024 * 1024
    file_id: str | None = None
    ext = ".jpg"

    if message.photo:
        file_id = message.photo[-1].file_id
        file_size = message.photo[-1].file_size or 0
        ext = ".jpg"
    elif message.document:
        doc = message.document
        allowed_exts = (".jpg", ".jpeg", ".png", ".webp")
        doc_ext = os.path.splitext(doc.file_name or "")[1].lower()
        if doc_ext not in allowed_exts:
            await message.answer("❌ Поддерживаются только .jpg, .jpeg, .png, .webp")
            return None
        file_id = doc.file_id
        file_size = doc.file_size or 0
        ext = doc_ext
    else:
        return None

    if file_size > max_bytes:
        await message.answer(f"❌ Файл слишком большой. Максимум {cfg['max_input_file_mb']} МБ.")
        return None

    tg_file = await bot.get_file(file_id)
    out_dir = os.path.join(settings.storage_base_path, "inputs", "merges")
    os.makedirs(out_dir, exist_ok=True)
    local_path = os.path.join(out_dir, f"{uuid4()}{ext}")
    await bot.download_file(tg_file.file_path, local_path)
    return local_path


async def _merge_proceed_to_next_step(message: Message, state: FSMContext, bot: Bot, photo_path: str):
    """После получения очередного фото: добавляем в список, переходим к следующему шагу или запускаем задачу."""
    data = await state.get_data()
    count = data.get("merge_count", 2)
    paths: list[str] = data.get("merge_photos_paths", [])
    paths.append(photo_path)
    await state.update_data(merge_photos_paths=paths)
    done = len(paths)
    telegram_id = str(message.from_user.id)

    try:
        with get_db_session() as db:
            AuditService(db).log(
                actor_type="user",
                actor_id=telegram_id,
                action="photo_merge_photo_uploaded",
                entity_type="user",
                entity_id=telegram_id,
                payload={"photo_num": done, "total": count},
            )
    except Exception:
        logger.exception("merge photo uploaded audit error")

    if done < count:
        next_num = done + 1
        next_state = BotStates.merge_waiting_photo_2 if next_num == 2 else BotStates.merge_waiting_photo_3
        await state.set_state(next_state)
        await message.answer(
            f"✅ Фото {done}/{count} получено!\n\n"
            f"📷 Теперь отправьте фото {next_num} из {count}."
        )
    else:
        await state.clear()
        progress_msg = await message.answer("⏳ Склеиваю фото, подождите…")
        try:
            with get_db_session() as db:
                cfg = PhotoMergeSettingsService(db).as_dict()
                job = PhotoMergeJob(
                    id=str(uuid4()),
                    user_id=telegram_id,
                    status="pending",
                    input_paths=paths,
                    input_count=count,
                    output_format=cfg["output_format"],
                )
                db.add(job)
                db.commit()
                job_id = job.id

            from app.workers.tasks.merge_photos import merge_photos as merge_task
            merge_task.apply_async(args=[job_id], queue="generation")

            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=progress_msg.message_id)
            except Exception:
                pass
            await message.answer(
                "🧩 Фото в обработке! Результат придёт сюда, обычно за 10–30 секунд.",
                reply_markup=main_menu_keyboard(),
            )
        except Exception:
            logger.exception("merge_proceed_start_task error")
            await message.answer("❌ Не удалось запустить обработку. Попробуйте ещё раз.")
            await message.answer("Выберите действие:", reply_markup=main_menu_keyboard())


@merge_router.message(BotStates.merge_waiting_photo_1, F.photo | F.document)
async def merge_recv_photo_1(message: Message, state: FSMContext, bot: Bot):
    with get_db_session() as db:
        cfg = PhotoMergeSettingsService(db).as_dict()
    path = await _download_merge_photo(message, bot, cfg)
    if path:
        await _merge_proceed_to_next_step(message, state, bot, path)


@merge_router.message(BotStates.merge_waiting_photo_2, F.photo | F.document)
async def merge_recv_photo_2(message: Message, state: FSMContext, bot: Bot):
    with get_db_session() as db:
        cfg = PhotoMergeSettingsService(db).as_dict()
    path = await _download_merge_photo(message, bot, cfg)
    if path:
        await _merge_proceed_to_next_step(message, state, bot, path)


@merge_router.message(BotStates.merge_waiting_photo_3, F.photo | F.document)
async def merge_recv_photo_3(message: Message, state: FSMContext, bot: Bot):
    with get_db_session() as db:
        cfg = PhotoMergeSettingsService(db).as_dict()
    path = await _download_merge_photo(message, bot, cfg)
    if path:
        await _merge_proceed_to_next_step(message, state, bot, path)


@merge_router.message(BotStates.merge_waiting_photo_1)
async def merge_wrong_input_1(message: Message):
    await message.answer("📷 Пожалуйста, отправьте фото или файл изображения (jpg, png, webp).")


@merge_router.message(BotStates.merge_waiting_photo_2)
async def merge_wrong_input_2(message: Message):
    await message.answer("📷 Пожалуйста, отправьте фото или файл изображения (jpg, png, webp).")


@merge_router.message(BotStates.merge_waiting_photo_3)
async def merge_wrong_input_3(message: Message):
    await message.answer("📷 Пожалуйста, отправьте фото или файл изображения (jpg, png, webp).")
