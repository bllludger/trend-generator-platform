import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from app.bot.helpers import t, tr, get_db_session, logger
from app.bot.keyboards import main_menu_keyboard
from app.core.config import settings
from app.services.users.service import UserService
from app.services.product_analytics.service import ProductAnalyticsService

commands_router = Router()

HELP_TEXT_DEFAULT = (
    "🎨 *NeoBanana — ИИ фотостудия*\n\n"
    "*Как использовать:*\n"
    "1. «🔥 Создать фото» — отправьте фото, выберите тренд, формат — результат!\n"
    "2. «🔄 Сделать такую же» — загрузите образец, затем своё фото — копия стиля 1:1\n"
    "3. «🛒 Купить пакет» — пакеты фото без водяного знака\n"
    "4. «👤 Мой профиль» — баланс и статистика\n\n"
    "*Как работает оплата:*\n"
    "— 3 бесплатных превью (с водяным знаком)\n"
    "— Купите пакет — оплата через ЮMoney (карта/кошелёк)\n"
    "— Можно разблокировать отдельное фото\n\n"
    "*Команды:*\n"
    "/start — Начать\n"
    "/help — Помощь\n"
    "/cancel — Отменить выбор\n"
    "/terms — Условия использования\n"
    "/paysupport — Поддержка по платежам\n"
    "Поддержка: @{support_username}\n\n"
    "*Форматы фото:* JPG, PNG, WEBP\n"
    "*Максимальный размер:* {max_file_size_mb} МБ"
)


@commands_router.message(Command("help"))
async def cmd_help(message: Message):
    """Handle /help command."""
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
                    ProductAnalyticsService(db).track("button_click", user.id, properties={"button_id": "help"})
            except Exception:
                logger.exception("button_click track failed help")
        await message.answer(
            tr("help.main_text", HELP_TEXT_DEFAULT, max_file_size_mb=settings.max_file_size_mb, support_username=settings.support_username),
            parse_mode="Markdown",
        )
    except Exception:
        logger.exception("Error in cmd_help")
        await message.answer(t("errors.try_later", "Произошла ошибка. Попробуйте позже."))


@commands_router.message(Command("trends"))
async def cmd_trends(message: Message):
    """Legacy: trends are shown after photo upload."""
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
                    ProductAnalyticsService(db).track("button_click", user.id, properties={"button_id": "trends"})
            except Exception:
                logger.exception("button_click track failed trends")
        await message.answer(
            t("flow.send_photo_first", "Сначала отправьте фото — после этого появятся тренды на выбор."),
            reply_markup=main_menu_keyboard(),
        )
    except Exception:
        logger.exception("Error in cmd_trends")
        await message.answer(t("errors.try_later", "Произошла ошибка. Попробуйте позже."))


@commands_router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Handle /cancel command."""
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
                    ProductAnalyticsService(db).track("button_click", user.id, properties={"button_id": "cancel"})
            except Exception:
                logger.exception("button_click track failed cancel")
        await state.clear()
        await message.answer(
            tr(
                "flow.cancelled",
                "❌ Выбор отменён.\n\nНажмите «{create_btn}» чтобы начать заново.",
                create_btn=t("menu.btn.create_photo", "🔥 Создать фото"),
            ),
            reply_markup=main_menu_keyboard(),
        )
    except Exception:
        logger.exception("Error in cmd_cancel")
        await message.answer(t("errors.try_later", "Произошла ошибка. Попробуйте позже."))
