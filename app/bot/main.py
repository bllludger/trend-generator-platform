"""
Telegram bot using aiogram 3.x
Clean and simple - no manual webhook/polling handling.
"""
import asyncio
import logging
import os
from contextlib import contextmanager
from typing import Any, Generator
from uuid import uuid4

from aiogram import Bot, Dispatcher, F, Router, BaseMiddleware
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
    ErrorEvent,
    TelegramObject,
    PreCheckoutQuery,
    LabeledPrice,
    ContentType,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.redis import RedisStorage
from sqlalchemy.orm import Session
import redis
from datetime import datetime, timezone

from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.services.audit.service import AuditService
from app.services.jobs.service import JobService
from app.services.themes.service import ThemeService
from app.services.trends.service import TrendService
from app.services.users.service import UserService
from app.services.security.settings_service import SecuritySettingsService
from app.services.bank_transfer.settings_service import BankTransferSettingsService
from app.services.idempotency import IdempotencyStore
from app.services.payments.service import PaymentService, PRODUCT_LADDER_IDS
from app.models.user import User
from app.models.job import Job
from app.models.bank_transfer_receipt_log import BankTransferReceiptLog
from app.paywall import record_unlock as paywall_record_unlock
from app.referral.config import get_min_pack_stars
from app.referral.service import ReferralService
from app.services.telegram_messages.runtime import runtime_templates
from app.services.generation_prompt.settings_service import GenerationPromptSettingsService
from app.utils.currency import format_stars_rub
from app.utils.telegram_photo import path_for_telegram_photo
from app.constants import AUDIENCE_COUPLES, AUDIENCE_MEN, AUDIENCE_WOMEN, audience_in_target_audiences
from app.utils.image_formats import ASPECT_RATIO_TO_SIZE
from app.services.balance_tariffs import build_balance_tariffs_message, _pack_outcome_label
from app.services.sessions.service import SessionService
from app.services.takes.service import TakeService
from app.services.favorites.service import FavoriteService
from app.services.hd_balance.service import HDBalanceService
from app.services.compensations.service import CompensationService
from app.models.pack import Pack
from app.models.session import Session as SessionModel
from app.models.take import Take as TakeModel
from app.models.trend import Trend as TrendModel

configure_logging()
logger = logging.getLogger("bot")


def t(key: str, default: str) -> str:
    return runtime_templates.get(key, default)


def tr(key: str, default: str, **variables: Any) -> str:
    return runtime_templates.render(key, default, **variables)


def _escape_markdown(s: str) -> str:
    """Экранировать символы для parse_mode='Markdown' (Telegram), чтобы * _ ` [ не ломали разбор."""
    if not s:
        return s
    for char, replacement in (("\\", "\\\\"), ("*", "\\*"), ("_", "\\_"), ("`", "\\`"), ("[", "\\[")):
        s = s.replace(char, replacement)
    return s


def _resolve_trend_example_path(stored_path: str | None, trend_id: str) -> str | None:
    """Резолв пути к файлу примера тренда: сначала сохранённый путь, иначе ищем по trend_examples_dir и шаблону {trend_id}_example.{ext} (как в API)."""
    if stored_path and os.path.isabs(stored_path) and os.path.isfile(stored_path):
        return stored_path
    base = getattr(settings, "trend_examples_dir", "data/trend_examples")
    if not os.path.isabs(base):
        base = os.path.join(os.getcwd(), base)
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        p = os.path.join(base, f"{trend_id}_example{ext}")
        if os.path.isfile(p):
            return p
    return None


# Welcome banner for /start (image/start_page.png в корне проекта)
_BOT_ROOT = os.path.dirname(os.path.abspath(__file__))
_PROJECT_IMAGE_DIR = os.path.join(_BOT_ROOT, "..", "..", "image")
WELCOME_IMAGE_PATH = os.path.join(_PROJECT_IMAGE_DIR, "start_page.png")
# Картинка к экрану «Выбор фотосессии» (баланс + тарифы)
MONEY_IMAGE_PATH = os.path.join(_PROJECT_IMAGE_DIR, "money2.png")
# Картинка к экрану «Загрузи своё фото» (правила для идеального кадра)
RULE_IMAGE_PATH = os.path.join(_PROJECT_IMAGE_DIR, "rule.png")
WELCOME_TEXT_DEFAULT = (
    "👋 Nano Banana — ИИ фотостудия\n\n"
    "Это просто фото.\n"
    "Но оно может стать сценой.\n\n"
    "Загрузи кадр — выбери стиль —\n"
    "получи результат как после съёмки.\n\n"
    "👇 Попробовать бесплатно"
)

# Image format options (aspect ratio -> size); общий маппинг с app.utils.image_formats
IMAGE_FORMATS = ASPECT_RATIO_TO_SIZE
TREND_CUSTOM_ID = "custom"  # Special ID for "Своя идея"
TRENDS_PER_PAGE = 6  # Трендов на одной странице внутри тематики
# Отбивка для ЦА «Мужчина» (тренды пока не поддерживаются)
AUDIENCE_MEN_OFFRAMP_TEXT = (
    "Извините, мы пока не работаем с мужскими профилями. "
    "Скоро добавим тренды для мужчин.\n\n"
    "Подпишитесь на канал, чтобы первыми узнать о запуске."
)
THEME_CB_PREFIX = "theme:"  # callback_data: theme:{id} или theme:{id}:{page}
NAV_THEMES = "nav:themes"   # Назад к тематикам

# Redis client for rate limiting
redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)


class SecurityMiddleware(BaseMiddleware):
    """
    Middleware to check user access:
    1. Check if user is banned → block
    2. Check if user is suspended → block until expires
    3. Check rate limit → block if exceeded
    """

    async def __call__(
        self,
        handler,
        event: TelegramObject,
        data: dict,
    ):
        # Extract user from event
        user_id = None
        if hasattr(event, 'from_user') and event.from_user:
            user_id = str(event.from_user.id)
        elif hasattr(event, 'message') and event.message and event.message.from_user:
            user_id = str(event.message.from_user.id)
        
        if not user_id:
            return await handler(event, data)
        
        # Check user status in DB
        try:
            with get_db_session() as db:
                user = db.query(User).filter(User.telegram_id == user_id).first()
                
                if user:
                    # Check ban
                    if user.is_banned:
                        msg = event if isinstance(event, Message) else getattr(event, 'message', None)
                        if msg:
                            await msg.answer(
                                tr("errors.banned", "🚫 Ваш аккаунт заблокирован.\n\nПричина: {reason}", reason=user.ban_reason or "Не указана")
                            )
                        logger.warning("Blocked banned user", extra={"user_id": user_id})
                        return  # Block handler
                    
                    # Check suspend
                    if user.is_suspended and user.suspended_until:
                        if datetime.now(timezone.utc) < user.suspended_until:
                            msg = event if isinstance(event, Message) else getattr(event, 'message', None)
                            if msg:
                                until_str = user.suspended_until.strftime("%d.%m.%Y %H:%M")
                                await msg.answer(
                                    tr("errors.suspended", "⏸ Ваш аккаунт временно приостановлен до {until}.\n\nПричина: {reason}", until=until_str, reason=user.suspend_reason or "Не указана")
                                )
                            logger.warning("Blocked suspended user", extra={"user_id": user_id})
                            return  # Block handler
                        else:
                            # Suspend expired, clear it
                            user.is_suspended = False
                            user.suspended_until = None
                            user.suspend_reason = None
                            db.commit()
                    
                    # Check rate limit (load from global settings)
                    sec_svc = SecuritySettingsService(db)
                    sec = sec_svc.get_or_create()
                    vip_bypass = bool(sec.vip_bypass_rate_limit and (user.flags or {}).get("VIP"))
                    if not vip_bypass:
                        rate_limit = user.get_effective_rate_limit(
                            default=sec.default_rate_limit_per_hour,
                            subscriber_limit=sec.subscriber_rate_limit_per_hour,
                        )
                        rate_key = f"rate_limit:{user_id}:{datetime.now(timezone.utc).strftime('%Y%m%d%H')}"
                        
                        try:
                            current = redis_client.incr(rate_key)
                            if current == 1:
                                redis_client.expire(rate_key, 3600)  # 1 hour TTL
                            
                            if current > rate_limit:
                                msg = event if isinstance(event, Message) else getattr(event, 'message', None)
                                if msg:
                                    await msg.answer(
                                        tr("errors.rate_limit", "⚠️ Превышен лимит запросов ({rate_limit}/час).\n\nПопробуйте через несколько минут.", rate_limit=rate_limit)
                                    )
                                logger.warning("Rate limit exceeded", extra={"user_id": user_id, "limit": rate_limit})
                                return  # Block handler
                        except redis.RedisError as e:
                            logger.warning(f"Redis error in rate limit check: {e}")
                            # Allow on Redis error - fail open
                else:
                    # User not in DB yet — rate limit by telegram_id (защита от спама до /start)
                    sec_svc = SecuritySettingsService(db)
                    sec = sec_svc.get_or_create()
                    rate_limit = sec.default_rate_limit_per_hour
                    rate_key = f"rate_limit:{user_id}:{datetime.now(timezone.utc).strftime('%Y%m%d%H')}"
                    try:
                        current = redis_client.incr(rate_key)
                        if current == 1:
                            redis_client.expire(rate_key, 3600)
                        if current > rate_limit:
                            msg = event if isinstance(event, Message) else getattr(event, 'message', None)
                            if msg:
                                await msg.answer(
                                    tr("errors.rate_limit", "⚠️ Превышен лимит запросов ({rate_limit}/час).\n\nПопробуйте через несколько минут.", rate_limit=rate_limit)
                                )
                            return
                    except redis.RedisError:
                        pass
        except Exception as e:
            logger.warning(f"Security middleware error: {e}")
            # Allow on error - fail open
        
        return await handler(event, data)


class SubscriptionMiddleware(BaseMiddleware):
    """
    Для новых пользователей: блокировать все действия кроме /start и кнопки «Я подписался»,
    пока не подписались на канал (subscription_channel_username).
    """
    async def __call__(self, handler, event: TelegramObject, data: dict):
        if not SUBSCRIPTION_CHANNEL_USERNAME:
            return await handler(event, data)
        user_id = None
        if hasattr(event, "from_user") and event.from_user:
            user_id = str(event.from_user.id)
        elif hasattr(event, "message") and event.message and event.message.from_user:
            user_id = str(event.message.from_user.id)
        if not user_id:
            return await handler(event, data)
        try:
            with get_db_session() as db:
                user = db.query(User).filter(User.telegram_id == user_id).first()
                if not user or _user_subscribed(user):
                    return await handler(event, data)
                # Пользователь есть, но не подписан — пропускаем только /start и subscription_check
                if isinstance(event, Message):
                    text = (event.text or "").strip()
                    if text.lower().startswith("/start"):
                        return await handler(event, data)
                    msg = event
                else:
                    # CallbackQuery
                    if getattr(event, "data", None) == SUBSCRIPTION_CALLBACK:
                        return await handler(event, data)
                    msg = getattr(event, "message", None)
                if msg:
                    kb = _subscription_keyboard()
                    await msg.answer(
                        t("subscription.prompt", SUBSCRIBE_TEXT_DEFAULT),
                        reply_markup=kb,
                    )
                    if hasattr(event, "answer"):
                        await event.answer()
                return
        except Exception as e:
            logger.warning(f"Subscription middleware error: {e}")
            return await handler(event, data)


HELP_TEXT_DEFAULT = (
    "🎨 *NanoBanan — ИИ фотостудия*\n\n"
    "*Как использовать:*\n"
    "1. «🔥 Создать фото» — отправьте фото, выберите тренд, формат — результат!\n"
    "2. «🔄 Сделать такую же» — загрузите образец, затем своё фото — копия стиля 1:1\n"
    "3. «🛒 Купить генерации» — пакеты фото за Telegram Stars (без watermark)\n"
    "4. «👤 Мой профиль» — баланс и статистика\n\n"
    "*Как работает оплата:*\n"
    "— 3 бесплатных превью (с watermark)\n"
    "— Купите пакет за Stars — получайте фото в полном качестве\n"
    "— Можно разблокировать отдельное фото\n\n"
    "*Команды:*\n"
    "/start — Начать\n"
    "/help — Помощь\n"
    "/cancel — Отменить выбор\n"
    "/terms — Условия использования\n"
    "/paysupport — Поддержка по платежам\n\n"
    "*Форматы фото:* JPG, PNG, WEBP\n"
    "*Максимальный размер:* {max_file_size_mb} МБ"
)

# Photo usage note (visual confirmation)
REFERENCE_NOTE_DEFAULT = "📎 Фото пользователя закреплены как Image B (REFERENCE) и будут участвовать в генерации."


# ===========================================
# Database session context manager
# ===========================================
@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """
    Context manager for database sessions.
    Handles commit on success and rollback on error.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ===========================================
# FSM States (2026 flow: photo → trend/idea → format → generate)
# ===========================================
class BotStates(StatesGroup):
    waiting_for_audience = State()        # Step 0: выбор ЦА (Женщина/Мужчина/Пара)
    waiting_for_photo = State()           # Step 1: upload photo
    waiting_for_trend = State()           # Step 2: select trend or "Своя идея"
    waiting_for_prompt = State()          # Step 2b: if "Своя идея" — user's text prompt
    waiting_for_format = State()          # Step 3: select aspect ratio
    # "Сделать такую же" flow
    waiting_for_reference_photo = State()  # Шаг 1: референс для копирования
    waiting_for_self_photo = State()       # Шаг 2: своё фото (1 или первое из 2)
    waiting_for_self_photo_2 = State()     # Шаг 2b: второе фото (если выбрано 2)
    # Оплата переводом на карту
    bank_transfer_waiting_receipt = State()  # Ждём чек (скриншот/фото)
    # Session-based flow (MVP)
    session_active = State()
    viewing_take_result = State()
    viewing_favorites = State()


# ===========================================
# Keyboards
# ===========================================
def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=t("menu.btn.create_photo", "🔥 Создать фото")),
                KeyboardButton(text=t("menu.btn.copy_style", "🔄 Сделать такую же")),
            ],
            [
                KeyboardButton(text=t("menu.btn.shop", "🛒 Купить тариф")),
                KeyboardButton(text=t("menu.btn.profile", "👤 Мой профиль")),
            ],
        ],
        resize_keyboard=True,
    )


def themes_keyboard(themes: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    """Клавиатура тематик (первый уровень после фото). Callback theme:{id}. В конце — Своя идея."""
    buttons: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(themes), 2):
        row = [
            InlineKeyboardButton(text=f"{t.get('emoji', '')} {t.get('name', '')}".strip(), callback_data=f"{THEME_CB_PREFIX}{t['id']}")
            for t in themes[i : i + 2]
        ]
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text=t("menu.btn.custom_idea", "💡 Своя идея"), callback_data=f"trend:{TREND_CUSTOM_ID}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def trends_in_theme_keyboard(
    theme_id: str,
    trends_page: list[dict[str, Any]],
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    """Клавиатура трендов одной тематики (страница N). До 6 трендов, навигация ‹ 1 2 3 ›, Назад к тематикам, В меню."""
    buttons: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(trends_page), 3):
        row = [
            InlineKeyboardButton(text=f"{t.get('emoji', '')} {t.get('name', '')}".strip(), callback_data=f"trend:{t['id']}")
            for t in trends_page[i : i + 3]
        ]
        buttons.append(row)
    nav_row: list[InlineKeyboardButton] = []
    if total_pages > 0:
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="‹", callback_data=f"{THEME_CB_PREFIX}{theme_id}:{page - 1}"))
        max_show = 5
        start = max(0, min(page - max_show // 2, total_pages - max_show))
        start = max(0, min(start, total_pages - max_show))
        for p in range(start, min(start + max_show, total_pages)):
            label = str(p + 1)
            if p == page:
                nav_row.append(InlineKeyboardButton(text=f"[{label}]", callback_data=f"{THEME_CB_PREFIX}{theme_id}:{p}"))
            else:
                nav_row.append(InlineKeyboardButton(text=label, callback_data=f"{THEME_CB_PREFIX}{theme_id}:{p}"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(text="›", callback_data=f"{THEME_CB_PREFIX}{theme_id}:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)
    buttons.append([
        InlineKeyboardButton(text=t("nav.btn.back_to_themes", "⬅️ Назад к тематикам"), callback_data=NAV_THEMES),
        InlineKeyboardButton(text=t("nav.btn.menu", "📋 В меню"), callback_data="nav:menu"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def trends_keyboard(trends: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    """Плоский список трендов (используется при deep link или если нет тематик)."""
    buttons = [
        [InlineKeyboardButton(text=f"{t['emoji']} {t['name']}", callback_data=f"trend:{t['id']}")]
        for t in trends
    ]
    buttons.append([InlineKeyboardButton(text=t("menu.btn.custom_idea", "💡 Своя идея"), callback_data=f"trend:{TREND_CUSTOM_ID}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def copy_photos_choice_keyboard() -> InlineKeyboardMarkup:
    """Инлайн-кнопки: 1 фото или 2 фото (для флоу «Сделать такую же»)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t("copy.btn.one_photo", "1 фотография"), callback_data="copy_photos:1"),
            InlineKeyboardButton(text=t("copy.btn.two_photos", "2 фотографии"), callback_data="copy_photos:2"),
        ],
    ])


def _get_default_aspect_ratio() -> str:
    """Дефолтный формат кадра из админки (Мастер промпт → На релиз → default_aspect_ratio)."""
    try:
        with get_db_session() as db:
            effective = GenerationPromptSettingsService(db).get_effective(profile="release")
            return (effective.get("default_aspect_ratio") or "1:1").strip()
    except Exception:
        return "1:1"


def _format_button_label(key: str, default_ar: str) -> str:
    """Текст кнопки формата; для дефолтного с админки добавляем « (по умолч.)»."""
    labels = {
        "1:1": t("format.btn.1_1", "1:1 Квадрат"),
        "16:9": t("format.btn.16_9", "16:9 Широкий"),
        "4:3": t("format.btn.4_3", "4:3 Классика"),
        "9:16": t("format.btn.9_16", "9:16 Портрет"),
        "3:4": t("format.btn.3_4", "3:4 Вертикальный"),
    }
    base = labels.get(key, key)
    return f"{base} (по умолч.)" if key == default_ar else base


def format_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора формата кадра. Дефолт из админки помечается « (по умолч.)»; выбор пользователя приоритетный."""
    default_ar = _get_default_aspect_ratio()
    buttons = [
        [
            InlineKeyboardButton(text=_format_button_label("1:1", default_ar), callback_data="format:1:1"),
            InlineKeyboardButton(text=_format_button_label("16:9", default_ar), callback_data="format:16:9"),
        ],
        [
            InlineKeyboardButton(text=_format_button_label("4:3", default_ar), callback_data="format:4:3"),
            InlineKeyboardButton(text=_format_button_label("9:16", default_ar), callback_data="format:9:16"),
        ],
        [InlineKeyboardButton(text=_format_button_label("3:4", default_ar), callback_data="format:3:4")],
        [
            InlineKeyboardButton(text=t("nav.btn.back_to_trends", "⬅️ Назад к трендам"), callback_data="nav:trends"),
            InlineKeyboardButton(text=t("nav.btn.menu", "📋 В меню"), callback_data="nav:menu"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ===========================================
# Router
# ===========================================
router = Router()


def patch_aiogram_message_methods() -> None:
    """Patch aiogram send helpers so any hardcoded literal can be overridden via templates."""
    if getattr(Message, "_tm_patched", False):
        return

    original_answer = Message.answer
    original_answer_photo = Message.answer_photo
    original_edit_text = Message.edit_text
    original_callback_answer = CallbackQuery.answer

    async def _answer(self, text: str, *args, **kwargs):
        if isinstance(text, str):
            text = runtime_templates.resolve_literal(text)
        return await original_answer(self, text, *args, **kwargs)

    async def _answer_photo(self, *args, **kwargs):
        caption = kwargs.get("caption")
        if isinstance(caption, str):
            kwargs["caption"] = runtime_templates.resolve_literal(caption)
        return await original_answer_photo(self, *args, **kwargs)

    async def _edit_text(self, text: str, *args, **kwargs):
        if isinstance(text, str):
            text = runtime_templates.resolve_literal(text)
        return await original_edit_text(self, text, *args, **kwargs)

    async def _cb_answer(self, text: str | None = None, *args, **kwargs):
        if isinstance(text, str):
            text = runtime_templates.resolve_literal(text)
        return await original_callback_answer(self, text=text, *args, **kwargs)

    Message.answer = _answer
    Message.answer_photo = _answer_photo
    Message.edit_text = _edit_text
    CallbackQuery.answer = _cb_answer
    Message._tm_patched = True


def _parse_start_raw_arg(text: str | None) -> str | None:
    """Extract raw argument from /start command. E.g. '/start ref_ABC' -> 'ref_ABC'."""
    if not text or not text.strip():
        return None
    parts = text.strip().split()
    if len(parts) < 2:
        return None
    return parts[1]


def _parse_start_arg(text: str | None) -> str | None:
    """Parse /start trend deep link. E.g. '/start trend_abc' -> 'abc'."""
    raw = _parse_start_raw_arg(text)
    if raw and raw.startswith("trend_"):
        return raw[6:]
    return None


def _parse_referral_code(text: str | None) -> str | None:
    """Parse /start referral deep link. E.g. '/start ref_ABCD1234' -> 'ABCD1234'."""
    raw = _parse_start_raw_arg(text)
    if raw and raw.startswith("ref_"):
        return raw[4:]
    return None


# Обязательная подписка на канал для новых пользователей
SUBSCRIPTION_CHANNEL_USERNAME = (getattr(settings, "subscription_channel_username", None) or "").strip()
SUBSCRIPTION_CALLBACK = "subscription_check"

SUBSCRIBE_TEXT_DEFAULT = (
    "👋 Чтобы пользоваться ботом, подпишитесь на канал с примерами — там идеи для фото и обновления.\n\n"
    "После подписки нажмите кнопку «Я подписался»."
)


def _subscription_keyboard():
    """Клавиатура: ссылка на канал + «Я подписался»."""
    if not SUBSCRIPTION_CHANNEL_USERNAME:
        return None
    channel_url = f"https://t.me/{SUBSCRIPTION_CHANNEL_USERNAME}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t("subscription.btn.channel", "📢 Перейти в канал"), url=channel_url)],
        [InlineKeyboardButton(text=t("subscription.btn.done", "✅ Я подписался"), callback_data=SUBSCRIPTION_CALLBACK)],
    ])


def _user_subscribed(user: User) -> bool:
    """Проверка: пользователь уже прошёл подписку на канал (флаг в flags)."""
    if not SUBSCRIPTION_CHANNEL_USERNAME:
        return True
    return bool((user.flags or {}).get("subscribed_examples_channel"))


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Handle /start command. Supports deep links: /start trend_<id>, /start ref_<code>."""
    telegram_id = str(message.from_user.id)
    u = message.from_user

    try:
        with get_db_session() as db:
            user_service = UserService(db)
            audit = AuditService(db)

            user_service.get_or_create_user(
                telegram_id,
                telegram_username=u.username,
                telegram_first_name=u.first_name,
                telegram_last_name=u.last_name,
            )
            user = user_service.get_by_telegram_id(telegram_id)

            audit.log(
                actor_type="user",
                actor_id=telegram_id,
                action="start",
                entity_type="session",
                entity_id=None,
                payload={},
            )

            ref_code = _parse_referral_code(message.text)
            if ref_code and user:
                audit.log(
                    actor_type="user",
                    actor_id=telegram_id,
                    action="referral_start",
                    entity_type="user",
                    entity_id=user.id,
                    payload={"referrer_code": ref_code},
                )
                ref_svc = ReferralService(db)
                attributed = ref_svc.attribute(user, ref_code)
                if attributed:
                    audit.log(
                        actor_type="user",
                        actor_id=telegram_id,
                        action="referral_attributed",
                        entity_type="user",
                        entity_id=user.id,
                        payload={"referrer_code": ref_code},
                    )

            # Обязательная подписка на канал для новых пользователей
            if SUBSCRIPTION_CHANNEL_USERNAME and user and not _user_subscribed(user):
                await state.clear()
                await state.update_data(
                    pending_start_arg=_parse_start_arg(message.text),
                    pending_ref_code=ref_code,
                )
                kb = _subscription_keyboard()
                await message.answer(
                    t("subscription.prompt", SUBSCRIBE_TEXT_DEFAULT),
                    reply_markup=kb,
                )
                logger.info("start_awaiting_subscription", extra={"user_id": telegram_id})
                return

            start_arg = _parse_start_arg(message.text)
            if start_arg:
                trend_service = TrendService(db)
                trend = trend_service.get(start_arg)
                if trend and trend.enabled:
                    await state.clear()
                    await state.update_data(
                        selected_trend_id=trend.id,
                        selected_trend_name=trend.name,
                    )
                    await state.set_state(BotStates.waiting_for_photo)
                    msg_text = tr(
                        "start.deeplink_trend",
                        "Отправьте фото — применим тренд «{name}»",
                        name=trend.name,
                    )
                    await message.answer(msg_text, reply_markup=main_menu_keyboard())
                    logger.info("start_deeplink_trend", extra={"user_id": telegram_id, "trend_id": trend.id})
                    return

        await state.clear()
        welcome_text = t("start.welcome_text", WELCOME_TEXT_DEFAULT)
        welcome_sent = False
        if os.path.exists(WELCOME_IMAGE_PATH):
            try:
                photo_path, is_temp = path_for_telegram_photo(WELCOME_IMAGE_PATH)
                await message.answer_photo(
                    photo=FSInputFile(photo_path),
                    caption=welcome_text,
                    reply_markup=main_menu_keyboard(),
                )
                welcome_sent = True
                if is_temp and os.path.isfile(photo_path):
                    try:
                        os.unlink(photo_path)
                    except OSError:
                        pass
            except Exception as e:
                logger.warning("start_welcome_photo_failed", extra={"path": WELCOME_IMAGE_PATH, "error": str(e)})
        if not welcome_sent:
            if not os.path.exists(WELCOME_IMAGE_PATH):
                logger.warning("start_welcome_image_not_found", extra={"path": WELCOME_IMAGE_PATH})
            await message.answer(welcome_text, reply_markup=main_menu_keyboard())
        logger.info("start", extra={"user_id": telegram_id})
    except Exception:
        logger.exception("Error in cmd_start", extra={"user_id": telegram_id})
        try:
            await message.answer(
                t("start.welcome_text", WELCOME_TEXT_DEFAULT),
                reply_markup=main_menu_keyboard(),
            )
        except Exception:
            await message.answer(t("errors.try_later", "Произошла ошибка. Попробуйте позже."))


@router.callback_query(F.data == SUBSCRIPTION_CALLBACK)
async def subscription_check(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Проверка подписки на канал и продолжение стартового сценария."""
    telegram_id = str(callback.from_user.id)
    try:
        chat_id = f"@{SUBSCRIPTION_CHANNEL_USERNAME}"
        member = await bot.get_chat_member(chat_id=chat_id, user_id=callback.from_user.id)
        status = (getattr(member, "status", None) or "").lower() if hasattr(member, "status") else ""
        if status not in ("member", "administrator", "creator"):
            await callback.answer(
                t("subscription.not_subscribed", "Сначала подпишитесь на канал, затем нажмите «Я подписался»."),
                show_alert=True,
            )
            return

        with get_db_session() as db:
            user_service = UserService(db)
            user = user_service.get_by_telegram_id(telegram_id)
            if user:
                flags = dict(user.flags or {})
                flags["subscribed_examples_channel"] = True
                user.flags = flags

        data = await state.get_data()
        pending_start_arg = data.get("pending_start_arg")
        await state.clear()

        # Продолжаем как после /start: диплинк или приветствие
        with get_db_session() as db:
            if pending_start_arg:
                trend_service = TrendService(db)
                trend = trend_service.get(pending_start_arg)
                if trend and trend.enabled:
                    await state.update_data(
                        selected_trend_id=trend.id,
                        selected_trend_name=trend.name,
                    )
                    await state.set_state(BotStates.waiting_for_photo)
                    msg_text = tr(
                        "start.deeplink_trend",
                        "Отправьте фото — применим тренд «{name}»",
                        name=trend.name,
                    )
                    await callback.message.answer(msg_text, reply_markup=main_menu_keyboard())
                    await callback.answer(t("subscription.done", "Спасибо! Добро пожаловать."))
                    return

        welcome_text = t("start.welcome_text", WELCOME_TEXT_DEFAULT)
        welcome_sent = False
        if os.path.exists(WELCOME_IMAGE_PATH):
            try:
                photo_path, is_temp = path_for_telegram_photo(WELCOME_IMAGE_PATH)
                await callback.message.answer_photo(
                    photo=FSInputFile(photo_path),
                    caption=welcome_text,
                    reply_markup=main_menu_keyboard(),
                )
                welcome_sent = True
                if is_temp and os.path.isfile(photo_path):
                    try:
                        os.unlink(photo_path)
                    except OSError:
                        pass
            except Exception as e:
                logger.warning("start_welcome_photo_failed", extra={"path": WELCOME_IMAGE_PATH, "error": str(e)})
        if not welcome_sent:
            if not os.path.exists(WELCOME_IMAGE_PATH):
                logger.warning("start_welcome_image_not_found", extra={"path": WELCOME_IMAGE_PATH})
            await callback.message.answer(welcome_text, reply_markup=main_menu_keyboard())
        await callback.answer(t("subscription.done", "Спасибо! Добро пожаловать."))
    except Exception as e:
        logger.exception("subscription_check error", extra={"user_id": telegram_id})
        await callback.answer(t("errors.try_later", "Произошла ошибка. Попробуйте позже."), show_alert=True)


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Handle /help command."""
    try:
        await message.answer(
            tr("help.main_text", HELP_TEXT_DEFAULT, max_file_size_mb=settings.max_file_size_mb),
            parse_mode="Markdown",
        )
    except Exception:
        logger.exception("Error in cmd_help")
        await message.answer(t("errors.try_later", "Произошла ошибка. Попробуйте позже."))


@router.message(Command("trends"))
async def cmd_trends(message: Message):
    """Legacy: trends are shown after photo upload."""
    try:
        await message.answer(
            t("flow.send_photo_first", "Сначала отправьте фото — после этого появятся тренды на выбор."),
            reply_markup=main_menu_keyboard(),
        )
    except Exception:
        logger.exception("Error in cmd_trends")
        await message.answer(t("errors.try_later", "Произошла ошибка. Попробуйте позже."))


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Handle /cancel command."""
    try:
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


# --- Мой профиль (баланс, бесплатные генерации) ---
@router.message(lambda m: (m.text or "").strip() == t("menu.btn.profile", "👤 Мой профиль"))
async def my_profile(message: Message):
    """Show user balance and free generations."""
    telegram_id = str(message.from_user.id)
    try:
        with get_db_session() as db:
            user_service = UserService(db)
            sec_svc = SecuritySettingsService(db)
            session_svc = SessionService(db)
            hd_svc = HDBalanceService(db)
            user = user_service.get_by_telegram_id(telegram_id)
            if not user:
                user = user_service.get_or_create_user(
                    telegram_id,
                    telegram_username=message.from_user.username,
                    telegram_first_name=message.from_user.first_name,
                    telegram_last_name=message.from_user.last_name,
                )
            sec = sec_svc.get_or_create()
            free_limit = getattr(sec, "free_generations_per_user", 3)
            free_used = getattr(user, "free_generations_used", 0)
            free_left = max(0, free_limit - free_used)
            copy_limit = getattr(sec, "copy_generations_per_user", 1)
            copy_used = getattr(user, "copy_generations_used", 0)
            copy_left = max(0, copy_limit - copy_used)
            token_balance = user.token_balance
            total_purchased = getattr(user, "total_purchased", 0)
            hd_credits = getattr(user, "hd_credits_balance", 0)
            show_referral = getattr(user, "has_purchased_hd", False)

            active_session = session_svc.get_active_session(user.id)
            plan_name = None
            remaining_takes = 0
            total_takes = 0
            hd_balance_total = 0
            if active_session:
                _pack = db.query(Pack).filter(Pack.id == active_session.pack_id).one_or_none()
                plan_name = _pack.name if _pack else active_session.pack_id
                remaining_takes = active_session.takes_limit - active_session.takes_used
                total_takes = active_session.takes_limit
                hd_balance_total = hd_svc.get_balance(user)["total"]

        text = t("profile.title", "👤 *Мой профиль*") + "\n\n"
        if plan_name:
            plan_safe = _escape_markdown(str(plan_name))
            text += (
                f"📦 *Текущий план:* {plan_safe}\n"
                f"📸 *Осталось снимков:* {remaining_takes} из {total_takes}\n"
                f"🖼 *4K без watermark:* {hd_balance_total}\n\n"
            )
        else:
            text += "📦 *Текущий план:* Нет активного плана\n\n"
        text += tr(
            "profile.body",
            "🆓 *Бесплатные превью:* {free_left} из {free_limit}\n"
            "🔄 *«Сделать такую же»:* {copy_left} из {copy_limit}\n"
            "💰 *Баланс генераций:* {token_balance}\n"
            "📊 *Всего куплено:* {total_purchased}\n\n"
            "Бесплатные генерации дают превью с watermark.\n"
            "Купите пакет — получайте фото в полном качестве!",
            free_left=free_left,
            free_limit=free_limit,
            copy_left=copy_left,
            copy_limit=copy_limit,
            token_balance=token_balance,
            total_purchased=total_purchased,
        )
        if hd_credits > 0:
            text += f"\n\n🎁 *Бонусы 4K:* {hd_credits}"

        buttons = [
            [InlineKeyboardButton(text=t("profile.btn.top_up", "🛒 Выбрать фотосессию"), callback_data="shop:open")],
        ]
        if show_referral:
            buttons.append([
                InlineKeyboardButton(text="💌 Пригласить подругу", callback_data="referral:invite"),
                InlineKeyboardButton(text="📊 Реферальный баланс", callback_data="referral:status"),
            ])
        profile_kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer(text, parse_mode="Markdown", reply_markup=profile_kb)
    except Exception:
        logger.exception("Error in my_profile")
        await message.answer(t("errors.profile_load", "Ошибка загрузки профиля."), reply_markup=main_menu_keyboard())


# --- Referral program screens ---

@router.callback_query(F.data == "referral:invite")
async def referral_invite(callback: CallbackQuery):
    """Show referral invite screen with personal link."""
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

        bot_username = settings.telegram_bot_username
        link = f"https://t.me/{bot_username}?start=ref_{code}" if bot_username else f"ref_{code}"
        min_stars = get_min_pack_stars()
        rate = getattr(settings, "star_to_rub", 1.3)
        min_price_str = format_stars_rub(min_stars, rate)

        text = (
            "💌 *Пригласи подругу — получи бонус на фотосессию*\n\n"
            f"Твоя персональная ссылка:\n`{link}`\n\n"
            "📌 *Условия:*\n"
            f"• Бонус начислим, когда подруга купит пакет от {min_price_str}\n"
            "• Бонус станет доступен через 12–24 часа\n"
            "• Работает для новых пользователей\n\n"
            "Поделись ссылкой — получи бонусы 4K!"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Скопировать ссылку", callback_data=f"referral:copy:{code}")],
            [
                InlineKeyboardButton(
                    text="📤 Поделиться",
                    switch_inline_query=f"Попробуй NanoBanan — крутые фото за 30 секунд! {link}",
                ),
            ],
            [InlineKeyboardButton(text="📊 Мой баланс", callback_data="referral:status")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="referral:back_profile")],
        ])
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
        await callback.answer()
    except Exception:
        logger.exception("Error in referral_invite")
        await callback.answer("Ошибка. Попробуйте позже.", show_alert=True)


@router.callback_query(F.data.startswith("referral:copy:"))
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


@router.callback_query(F.data == "referral:status")
async def referral_status(callback: CallbackQuery):
    """Show referral balance and stats."""
    telegram_id = str(callback.from_user.id)
    try:
        with get_db_session() as db:
            user_service = UserService(db)
            user = user_service.get_by_telegram_id(telegram_id)
            if not user:
                await callback.answer("Пользователь не найден.", show_alert=True)
                return

            ref_svc = ReferralService(db)
            stats = ref_svc.get_referral_stats(user.id)
            hd_debt = getattr(user, "hd_credits_debt", 0)

        text = (
            "📊 *Реферальная программа*\n\n"
            f"👥 Приглашено: {stats['attributed']}\n"
            f"💰 Купили пакет: {stats['bought']}\n\n"
            f"🎁 *Бонусы 4K:*\n"
            f"  Доступно: {stats['available']}\n"
            f"  В ожидании: {stats['pending']}\n"
            f"  Потрачено: {stats['spent']}\n"
        )
        if hd_debt > 0:
            text += f"  ⚠️ Долг: {hd_debt}\n"
        text += "\nБонусы 4K можно использовать при разблокировке фото."

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💌 Пригласить ещё", callback_data="referral:invite")],
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


@router.callback_query(F.data == "referral:back_profile")
async def referral_back_to_profile(callback: CallbackQuery):
    """Return to profile from referral screen."""
    try:
        try:
            await callback.message.delete()
        except Exception:
            pass
        fake_msg = callback.message
        fake_msg.from_user = callback.from_user
        await my_profile(fake_msg)
    except Exception:
        logger.exception("Error in referral_back_to_profile")
        await callback.message.answer(t("errors.profile_load", "Ошибка загрузки профиля."), reply_markup=main_menu_keyboard())
    await callback.answer()


# --- Step 0: Request photo ---
REQUEST_PHOTO_TEXT_DEFAULT = (
    "📸 Загрузи своё фото\n"
    "и получи съёмку как из дорогой студии — за 30 секунд\n\n"
    "✨ Превью бесплатно\n\n"
    "Чтобы получилось идеально:\n"
    "— лицо крупно в кадре\n"
    "— без очков\n"
    "— фото чёткое\n\n"
    "👇 Попробовать"
)


def audience_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора ЦА: Женщина, Мужчина, Пара."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t("audience.women", "👩 Женщина"), callback_data="audience:women"),
            InlineKeyboardButton(text=t("audience.men", "👨 Мужчина"), callback_data="audience:men"),
        ],
        [InlineKeyboardButton(text=t("audience.couples", "👫 Пара"), callback_data="audience:couples")],
    ])


@router.message(lambda m: (m.text or "").strip() == t("menu.btn.create_photo", "🔥 Создать фото"))
async def request_photo(message: Message, state: FSMContext, bot: Bot):
    """User clicks 'Create photo' → сначала выбор ЦА, затем запрос фото."""
    try:
        await state.set_state(BotStates.waiting_for_audience)
        sent = await message.answer(
            t("audience.prompt", "Для кого создаём образ?"),
            reply_markup=audience_keyboard(),
        )
        await state.update_data(last_bot_message_id=sent.message_id)
    except Exception:
        logger.exception("Error in request_photo")
        await message.answer(t("errors.try_later", "Произошла ошибка. Попробуйте позже."), reply_markup=main_menu_keyboard())


@router.callback_query(F.data.startswith("audience:"))
async def on_audience_selected(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Выбор ЦА: сохраняем в state, логируем audit, переходим к запросу фото."""
    audience = callback.data.replace("audience:", "").strip().lower()
    if audience not in (AUDIENCE_WOMEN, AUDIENCE_MEN, AUDIENCE_COUPLES):
        await callback.answer()
        return
    try:
        await state.update_data(audience_type=audience)
        await state.set_state(BotStates.waiting_for_photo)
        await callback.answer()

        telegram_id = str(callback.from_user.id) if callback.from_user else None
        if telegram_id:
            try:
                with get_db_session() as db:
                    AuditService(db).log(
                        actor_type="user",
                        actor_id=telegram_id,
                        action="audience_selected",
                        entity_type="user",
                        entity_id=telegram_id,
                        payload={"audience": audience},
                    )
            except Exception as e:
                logger.warning("Audit audience_selected failed: %s", e)

        audience_label = {"women": "Женщина", "men": "Мужчина", "couples": "Пара"}.get(audience, audience)
        request_text = t("flow.request_photo", REQUEST_PHOTO_TEXT_DEFAULT)
        if os.path.exists(RULE_IMAGE_PATH):
            try:
                await callback.message.delete()
                photo_path, is_temp = path_for_telegram_photo(RULE_IMAGE_PATH)
                sent = await callback.message.answer_photo(
                    photo=FSInputFile(photo_path),
                    caption=request_text,
                    parse_mode="HTML",
                )
                if is_temp and os.path.isfile(photo_path):
                    try:
                        os.unlink(photo_path)
                    except OSError:
                        pass
            except Exception as e:
                logger.warning("rule_photo_failed", extra={"path": RULE_IMAGE_PATH, "error": str(e)})
                sent = await callback.message.answer(request_text, parse_mode="HTML")
        else:
            await callback.message.edit_text(request_text, parse_mode="HTML")
            sent = None
        if sent is None:
            sent = await callback.message.answer(
                t("audience.selected_then_upload", "Выбрано: {audience}. Отправьте фото или нажмите «🔥 Создать фото».").replace("{audience}", audience_label),
                reply_markup=main_menu_keyboard(),
            )
        else:
            sent = await callback.message.answer(
                t("audience.selected_then_upload", "Выбрано: {audience}. Отправьте фото или нажмите «🔥 Создать фото».").replace("{audience}", audience_label),
                reply_markup=main_menu_keyboard(),
            )
        await state.update_data(last_bot_message_id=sent.message_id)
    except Exception:
        logger.exception("Error in on_audience_selected")
        await callback.answer(t("errors.try_later", "Произошла ошибка. Попробуйте позже."), show_alert=True)
        try:
            await callback.message.answer(
                t("nav.upload_photo_or_btn", "Отправьте фото или нажмите «🔥 Создать фото»."),
                reply_markup=main_menu_keyboard(),
            )
        except Exception:
            pass


# --- "Сделать такую же" flow ---
@router.message(lambda m: (m.text or "").strip() == t("menu.btn.copy_style", "🔄 Сделать такую же"))
async def start_copy_flow(message: Message, state: FSMContext, bot: Bot):
    """Начало флоу копирования стиля 1:1."""
    try:
        await state.set_state(BotStates.waiting_for_reference_photo)
        sent = await message.answer(
            t(
                "copy.start_text",
                "🔄 *Сделать такую же*\n\n"
                "Я могу скопировать 1:1 любой тренд.\n\n"
                "Загрузи картинку-образец в хорошем качестве — "
                "я изучу дизайн и подскажу, как сделать такую же.\n\n"
                "Поддерживаются: JPG, PNG, WEBP.",
            ),
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
        await state.update_data(last_bot_message_id=sent.message_id)
    except Exception:
        logger.exception("Error in start_copy_flow")
        await message.answer(t("errors.try_later", "Произошла ошибка. Попробуйте позже."), reply_markup=main_menu_keyboard())


@router.message(BotStates.waiting_for_reference_photo, F.photo)
async def handle_reference_photo(message: Message, state: FSMContext, bot: Bot):
    """Принимаем референс, вызываем LLM Vision, просим своё фото."""
    telegram_id = str(message.from_user.id)
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

    analyzing_msg = await message.answer(t("flow.analyzing", "⏳ Анализирую дизайн..."))
    try:
        from app.services.llm.vision_analyzer import analyze_reference_image
        copy_prompt = await asyncio.to_thread(analyze_reference_image, local_path)
    except Exception as e:
        logger.exception("Vision analysis failed")
        await analyzing_msg.edit_text(
            f"Не удалось проанализировать фото. Попробуйте другое изображение в хорошем качестве."
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
    data = await state.get_data()
    await _try_delete_messages(bot, message.chat.id, data.get("last_bot_message_id"), message.message_id)
    await state.update_data(
        copy_prompt=copy_prompt,
        reference_path=local_path,
        copy_photos_count=1,
    )
    await state.set_state(BotStates.waiting_for_self_photo)
    sent = await message.answer(
        "✅ Круто! Я изучил дизайн.\n\n"
        "Сколько фотографий загрузить? Выбери:",
        parse_mode="Markdown",
        reply_markup=copy_photos_choice_keyboard(),
    )
    await state.update_data(last_bot_message_id=sent.message_id)


@router.message(BotStates.waiting_for_reference_photo, F.document)
async def handle_reference_photo_as_document(message: Message, state: FSMContext, bot: Bot):
    """Принимаем референс, отправленный как файл (документ) — тот же флоу, что и фото."""
    doc = message.document
    if not doc:
        await message.answer(t("errors.try_later_short", "Ошибка. Попробуйте позже."))
        return
    ext = _document_image_ext(doc.mime_type, doc.file_name)
    if not ext:
        await message.answer(t("flow.only_images", "Поддерживаются только изображения: JPG, PNG, WEBP. Отправьте файл с фото."))
        return
    telegram_id = str(message.from_user.id)
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

    analyzing_msg = await message.answer(t("flow.analyzing", "⏳ Анализирую дизайн..."))
    try:
        from app.services.llm.vision_analyzer import analyze_reference_image
        copy_prompt = await asyncio.to_thread(analyze_reference_image, local_path)
    except Exception:
        logger.exception("Vision analysis failed (reference document)")
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
    data = await state.get_data()
    await _try_delete_messages(bot, message.chat.id, data.get("last_bot_message_id"), message.message_id)
    await state.update_data(
        copy_prompt=copy_prompt,
        reference_path=local_path,
        copy_photos_count=1,
    )
    await state.set_state(BotStates.waiting_for_self_photo)
    sent = await message.answer(
        "✅ Круто! Я изучил дизайн.\n\n"
        "Сколько фотографий загрузить? Выбери:",
        parse_mode="Markdown",
        reply_markup=copy_photos_choice_keyboard(),
    )
    await state.update_data(last_bot_message_id=sent.message_id)


@router.callback_query(F.data.startswith("copy_photos:"))
async def copy_photos_choice(callback: CallbackQuery, state: FSMContext):
    """Пользователь выбрал 1 или 2 фотографии в флоу «Сделать такую же»."""
    count_str = callback.data.split(":", 1)[1]
    if count_str not in ("1", "2"):
        await callback.answer(t("copy.choose_one_two", "Выбери 1 или 2."), show_alert=True)
        return
    count = int(count_str)
    await state.update_data(copy_photos_count=count)
    if count == 1:
        await callback.message.edit_text(
            "✅ Круто! Я изучил дизайн.\n\n"
            "Отправьте *одну* фотографию — сделаю такое же изображение.",
            parse_mode="Markdown",
        )
        await callback.answer(t("copy.wait_one_photo", "Жду одну фотографию."))
    else:
        await callback.message.edit_text(
            "✅ Круто! Я изучил дизайн.\n\n"
            "Отправьте *две* фотографии по очереди. Сначала первую:",
            parse_mode="Markdown",
        )
        await callback.answer(t("copy.wait_two_photos", "Жду две фотографии."))


@router.message(BotStates.waiting_for_self_photo, F.photo)
async def handle_self_photo_for_copy(message: Message, state: FSMContext, bot: Bot):
    """Принимаем своё фото (1-е или единственное), сохраняем; при 2 фото — ждём второе."""
    telegram_id = str(message.from_user.id)
    data = await state.get_data()
    copy_prompt = data.get("copy_prompt")
    if not copy_prompt:
        await message.answer(t("flow.session_expired_copy", "Сессия истекла. Начните заново: «🔄 Сделать такую же»."))
        await state.clear()
        return

    copy_photos_count = data.get("copy_photos_count", 1)
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
    if copy_photos_count == 2:
        received = data.get("copy_photos_received") or []
        received.append({"file_id": photo.file_id, "path": local_path})
        await state.update_data(
            copy_photos_received=received,
            selected_trend_id=TREND_CUSTOM_ID,
            custom_prompt=copy_prompt,
        )
        await state.set_state(BotStates.waiting_for_self_photo_2)
        sent = await message.answer(
            "✅ Первое фото получено.\n"
            f"{t('flow.reference_note', REFERENCE_NOTE_DEFAULT)}\n\n"
            "Отправьте вторую фотографию."
        )
        await state.update_data(last_bot_message_id=sent.message_id)
        return

    await state.update_data(
        photo_file_id=photo.file_id,
        photo_local_path=local_path,
        selected_trend_id=TREND_CUSTOM_ID,
        custom_prompt=copy_prompt,
    )
    await state.set_state(BotStates.waiting_for_format)
    sent = await message.answer(
        "✅ Фото получено!\n"
        f"{t('flow.reference_note', REFERENCE_NOTE_DEFAULT)}\n\n"
        "Выбери формат:",
        reply_markup=format_keyboard(),
    )
    await state.update_data(last_bot_message_id=sent.message_id)


@router.message(BotStates.waiting_for_self_photo, F.document)
async def handle_self_photo_as_document_for_copy(message: Message, state: FSMContext, bot: Bot):
    """Принимаем своё фото (1-е или единственное), отправленное как документ."""
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
    copy_prompt = data.get("copy_prompt")
    if not copy_prompt:
        await message.answer(t("flow.session_expired_copy", "Сессия истекла. Начните заново: «🔄 Сделать такую же»."))
        await state.clear()
        return

    copy_photos_count = data.get("copy_photos_count", 1)
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
    if copy_photos_count == 2:
        received = data.get("copy_photos_received") or []
        received.append({"file_id": doc.file_id, "path": local_path})
        await state.update_data(
            copy_photos_received=received,
            selected_trend_id=TREND_CUSTOM_ID,
            custom_prompt=copy_prompt,
        )
        await state.set_state(BotStates.waiting_for_self_photo_2)
        sent = await message.answer(
            "✅ Первое фото получено.\n"
            f"{t('flow.reference_note', REFERENCE_NOTE_DEFAULT)}\n\n"
            "Отправьте вторую фотографию."
        )
        await state.update_data(last_bot_message_id=sent.message_id)
        return

    await state.update_data(
        photo_file_id=doc.file_id,
        photo_local_path=local_path,
        selected_trend_id=TREND_CUSTOM_ID,
        custom_prompt=copy_prompt,
    )
    await state.set_state(BotStates.waiting_for_format)
    sent = await message.answer(
        "✅ Фото получено!\n"
        f"{t('flow.reference_note', REFERENCE_NOTE_DEFAULT)}\n\n"
        "Выбери формат:",
        reply_markup=format_keyboard(),
    )
    await state.update_data(last_bot_message_id=sent.message_id)


@router.message(BotStates.waiting_for_self_photo_2, F.photo)
async def handle_self_photo_2_for_copy(message: Message, state: FSMContext, bot: Bot):
    """Принимаем второе фото в флоу «2 фотографии»."""
    data = await state.get_data()
    copy_photos_received = data.get("copy_photos_received") or []
    if len(copy_photos_received) != 1:
        await message.answer(t("flow.session_reset_copy", "Сессия сброшена. Начните заново: «🔄 Сделать такую же»."))
        await state.clear()
        return

    photo = message.photo[-1]
    try:
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
        logger.exception("Failed to save second photo for copy")
        await message.answer(t("flow.save_photo_error", "Не удалось сохранить фото. Попробуйте ещё раз."))
        return

    data = await state.get_data()
    await _try_delete_messages(bot, message.chat.id, data.get("last_bot_message_id"), message.message_id)
    received = copy_photos_received + [{"file_id": photo.file_id, "path": local_path}]
    first = received[0]
    await state.update_data(
        copy_photos_received=received,
        photo_file_id=first["file_id"],
        photo_local_path=first["path"],
    )
    await state.set_state(BotStates.waiting_for_format)
    sent = await message.answer(
        "✅ Оба фото получены!\n"
        f"{t('flow.reference_note', REFERENCE_NOTE_DEFAULT)}\n\n"
        "Выбери формат:",
        reply_markup=format_keyboard(),
    )
    await state.update_data(last_bot_message_id=sent.message_id)


@router.message(BotStates.waiting_for_self_photo_2, F.document)
async def handle_self_photo_2_as_document_for_copy(message: Message, state: FSMContext, bot: Bot):
    """Принимаем второе фото как документ в флоу «2 фотографии»."""
    doc = message.document
    if not doc:
        await message.answer(t("errors.try_later_short", "Ошибка. Попробуйте позже."))
        return
    ext = _document_image_ext(doc.mime_type, doc.file_name)
    if not ext:
        await message.answer(t("flow.only_images", "Поддерживаются только изображения: JPG, PNG, WEBP."))
        return
    data = await state.get_data()
    copy_photos_received = data.get("copy_photos_received") or []
    if len(copy_photos_received) != 1:
        await message.answer(t("flow.session_reset_copy", "Сессия сброшена. Начните заново: «🔄 Сделать такую же»."))
        await state.clear()
        return

    try:
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
        logger.exception("Failed to save second photo for copy (document)")
        await message.answer(t("flow.save_file_error", "Не удалось сохранить файл. Попробуйте ещё раз."))
        return

    data = await state.get_data()
    await _try_delete_messages(bot, message.chat.id, data.get("last_bot_message_id"), message.message_id)
    received = copy_photos_received + [{"file_id": doc.file_id, "path": local_path}]
    first = received[0]
    await state.update_data(
        copy_photos_received=received,
        photo_file_id=first["file_id"],
        photo_local_path=first["path"],
    )
    await state.set_state(BotStates.waiting_for_format)
    sent = await message.answer(
        "✅ Оба фото получены!\n"
        f"{t('flow.reference_note', REFERENCE_NOTE_DEFAULT)}\n\n"
        "Выбери формат:",
        reply_markup=format_keyboard(),
    )
    await state.update_data(last_bot_message_id=sent.message_id)


@router.message(BotStates.waiting_for_self_photo_2)
async def copy_flow_wrong_input_self_2(message: Message):
    await message.answer(t("flow.send_second_photo", "Отправьте вторую фотографию (фото или файл изображения)."))


@router.message(BotStates.waiting_for_reference_photo)
async def copy_flow_wrong_input_ref(message: Message):
    await message.answer(t("flow.send_reference", "Отправьте картинку-образец (фото)."))


@router.message(BotStates.waiting_for_self_photo)
async def copy_flow_wrong_input_self(message: Message):
    await message.answer(t("flow.send_your_photo", "Отправьте свою фотографию."))


async def _try_delete_messages(bot: Bot, chat_id: int, *message_ids: int) -> None:
    """Мягкое исчезновение: сворачиваем текст в точку, пауза, затем удаление. Фото — сразу удаление."""
    valid_ids = [mid for mid in message_ids if mid is not None]
    if not valid_ids:
        return
    empty_markup = InlineKeyboardMarkup(inline_keyboard=[])
    for mid in valid_ids:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=mid,
                text="·",
                reply_markup=empty_markup,
            )
        except Exception:
            pass
    await asyncio.sleep(0.28)
    for mid in valid_ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass


def _document_image_ext(mime_type: str | None, file_name: str | None) -> str | None:
    """Return allowed image extension from document mime/name, or None if not image."""
    allowed = (".jpg", ".jpeg", ".png", ".webp")
    if file_name:
        ext = os.path.splitext(file_name)[1].lower()
        if ext in allowed:
            return ext
    if mime_type:
        m = (mime_type or "").strip().lower()
        if m in ("image/jpeg", "image/jpg"):
            return ".jpg"
        if m == "image/png":
            return ".png"
        if m == "image/webp":
            return ".webp"
    return None


# --- Consent + Data Deletion ---

@router.callback_query(F.data == "accept_consent")
async def accept_consent(callback: CallbackQuery, state: FSMContext):
    """User accepts privacy consent."""
    telegram_id = str(callback.from_user.id)
    try:
        with get_db_session() as db:
            user_svc = UserService(db)
            user = user_svc.get_or_create_user(
                telegram_id,
                telegram_username=callback.from_user.username,
                telegram_first_name=callback.from_user.first_name,
                telegram_last_name=callback.from_user.last_name,
            )
            user.consent_accepted_at = datetime.now(timezone.utc)
            db.add(user)

        await callback.answer("✅ Согласие принято")
        await callback.message.answer(
            "👍 Отлично! Теперь отправьте фото.",
            reply_markup=main_menu_keyboard(),
        )
    except Exception:
        logger.exception("accept_consent error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)


@router.message(Command("deletemydata"))
async def cmd_delete_my_data(message: Message, state: FSMContext):
    """User requests deletion of all their data."""
    telegram_id = str(message.from_user.id)
    try:
        with get_db_session() as db:
            user_svc = UserService(db)
            user = user_svc.get_or_create_user(
                telegram_id,
                telegram_username=message.from_user.username,
                telegram_first_name=message.from_user.first_name,
                telegram_last_name=message.from_user.last_name,
            )
            user.data_deletion_requested_at = datetime.now(timezone.utc)
            db.add(user)
            user_id = user.id

        from app.core.celery_app import celery_app as _celery
        _celery.send_task(
            "app.workers.tasks.delete_user_data.delete_user_data",
            args=[user_id],
        )
        await message.answer(
            "🗑 Запрос на удаление данных принят.\n"
            "Данные будут удалены в течение 72 часов.\n"
            "Мы уведомим вас о завершении."
        )
    except Exception:
        logger.exception("cmd_delete_my_data error", extra={"user_id": telegram_id})
        await message.answer("❌ Ошибка при запросе удаления данных.")


# --- Step 1: Receive photo, save and show trends ---
@router.message(BotStates.waiting_for_photo, F.photo)
async def handle_photo_step1(message: Message, state: FSMContext, bot: Bot):
    """Save photo and show trend selection (or 'Своя идея')."""
    telegram_id = str(message.from_user.id)
    
    try:
        # Consent check
        with get_db_session() as db:
            user_svc_consent = UserService(db)
            u_consent = user_svc_consent.get_or_create_user(
                telegram_id,
                telegram_username=message.from_user.username,
                telegram_first_name=message.from_user.first_name,
                telegram_last_name=message.from_user.last_name,
            )
            if not u_consent.consent_accepted_at:
                await message.answer(
                    "📋 Перед загрузкой фото подтвердите согласие:\n\n"
                    "• Используйте только свои фото или фото с согласием владельца\n"
                    "• Входные данные хранятся 30 дней, результаты — 90 дней\n"
                    "• Вы можете удалить данные командой /deletemydata\n\n"
                    "Нажмите «Принимаю» чтобы продолжить.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Принимаю", callback_data="accept_consent")],
                        [InlineKeyboardButton(text="ℹ️ Подробнее", url="https://nanobanana.ai/privacy")],
                    ]),
                )
                return

        data_early = await state.get_data()
        audience = (data_early.get("audience_type") or "").strip().lower() or AUDIENCE_WOMEN
        if audience == AUDIENCE_MEN:
            await message.answer(
                t("audience.men_offramp", AUDIENCE_MEN_OFFRAMP_TEXT),
                reply_markup=main_menu_keyboard(),
            )
            await state.clear()
            return

        # Validate photo
        photo = message.photo[-1]
        _, ext = os.path.splitext(photo.file_id)
        if ext and ext.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            await message.answer(t("flow.only_jpg_png_webp", "Поддерживаются только JPG, PNG, WEBP."))
            return

        with get_db_session() as db:
            user_service = UserService(db)
            theme_service = ThemeService(db)
            trend_service = TrendService(db)
            u = message.from_user
            user_service.get_or_create_user(
                telegram_id,
                telegram_username=u.username,
                telegram_first_name=u.first_name,
                telegram_last_name=u.last_name,
            )
            theme_ids_with_trends = trend_service.list_theme_ids_with_active_trends(audience)
            all_themes = theme_service.list_all()
            themes = [t for t in all_themes if t.enabled and t.id in theme_ids_with_trends]
            themes_data = [{"id": t.id, "name": t.name, "emoji": t.emoji or ""} for t in themes]

            # Download and save photo
            file = await bot.get_file(photo.file_id)
            inputs_dir = os.path.join(settings.storage_base_path, "inputs")
            os.makedirs(inputs_dir, exist_ok=True)
            local_path = os.path.join(inputs_dir, f"{photo.file_id}.jpg")
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
        
        await state.update_data(
            photo_file_id=photo.file_id,
            photo_local_path=local_path,
        )
        data = await state.get_data()

        # Collection: first photo for the whole session — save to session and start step 0
        with get_db_session() as db:
            user_svc = UserService(db)
            session_svc = SessionService(db)
            u = user_svc.get_or_create_user(
                telegram_id,
                telegram_username=message.from_user.username,
                telegram_first_name=message.from_user.first_name,
                telegram_last_name=message.from_user.last_name,
            )
            session = session_svc.get_active_session(u.id)
            if session and session_svc.is_collection(session) and not session.input_photo_path:
                session_svc.set_input_photo(session, local_path, photo.file_id)
                trend_id = session_svc.get_next_trend_id(session)
                if trend_id:
                    trend_svc = TrendService(db)
                    take_svc = TakeService(db)
                    trend = trend_svc.get(trend_id)
                    trend_name = trend.name if trend else trend_id
                    take = take_svc.create_take(
                        user_id=u.id,
                        trend_id=trend_id,
                        input_file_ids=[photo.file_id],
                        input_local_paths=[local_path],
                        image_size="1024x1024",
                    )
                    take.step_index = 0
                    take.is_reroll = False
                    db.add(take)
                    session_svc.attach_take_to_session(take, session)
                    session_svc.advance_step(session)
                    take_id = take.id

                    from app.core.celery_app import celery_app as _celery
                    status_msg = await message.answer(f"⏳ Образ 1 из {len(session.playlist)} — {trend_name}...")
                    _celery.send_task(
                        "app.workers.tasks.generate_take.generate_take",
                        args=[take_id],
                        kwargs={
                            "status_chat_id": str(message.chat.id),
                            "status_message_id": status_msg.message_id,
                        },
                    )
                    await state.set_state(BotStates.viewing_take_result)
                    return

        data = await state.get_data()
        audience = (data.get("audience_type") or "").strip().lower() or AUDIENCE_WOMEN
        # Deep link: trend already selected — skip trend choice, go to format (проверяем ЦА)
        pre_selected_id = data.get("selected_trend_id")
        if pre_selected_id and pre_selected_id != TREND_CUSTOM_ID:
            with get_db_session() as db:
                trend = TrendService(db).get(pre_selected_id)
                if trend and trend.enabled:
                    if not audience_in_target_audiences(audience, getattr(trend, "target_audiences", None)):
                        await message.answer(
                            t("audience.trend_unavailable_audience", "Тренд недоступен для выбранной целевой аудитории."),
                            reply_markup=main_menu_keyboard(),
                        )
                        await state.clear()
                        return
                    await state.set_state(BotStates.waiting_for_format)
                    await _try_delete_messages(bot, message.chat.id, data.get("last_bot_message_id"), message.message_id)
                    trend_name = trend.name
                    trend_emoji = trend.emoji or ""
                    example_path = _resolve_trend_example_path(getattr(trend, "example_image_path", None), str(trend.id))
                    if example_path:
                        try:
                            sent = await message.answer_photo(
                                photo=FSInputFile(example_path),
                                caption=(
                                    f"✅ Фото принято. Тренд: {trend_emoji} {trend_name}\n\n"
                                    "Выберите формат кадра:"
                                ),
                                reply_markup=format_keyboard(),
                            )
                        except Exception:
                            sent = await message.answer(
                                f"✅ Фото принято. Тренд: {trend_emoji} {trend_name}\n\nВыберите формат кадра:",
                                reply_markup=format_keyboard(),
                            )
                    else:
                        sent = await message.answer(
                            f"✅ Фото принято. Тренд: {trend_emoji} {trend_name}\n\nВыберите формат кадра:",
                            reply_markup=format_keyboard(),
                        )
                    await state.update_data(last_bot_message_id=sent.message_id)
                    logger.info("photo_received_deeplink", extra={"user_id": telegram_id, "trend_id": pre_selected_id})
                    return
        await state.set_state(BotStates.waiting_for_trend)
        await _try_delete_messages(bot, message.chat.id, data.get("last_bot_message_id"), message.message_id)
        caption = t("flow.photo_accepted_choose_theme", "✅ Фото принято\n\nМы используем его, чтобы сохранить вашу внешность и стиль.\nВыберите тематику или придумайте свой образ 👇")
        sent = await message.answer(
            caption,
            reply_markup=themes_keyboard(themes_data),
        )
        await state.update_data(last_bot_message_id=sent.message_id)
        logger.info("photo_received", extra={"user_id": telegram_id})
    except Exception:
        logger.exception("Error in handle_photo_step1", extra={"user_id": telegram_id})
        await message.answer(t("errors.upload_photo", "Ошибка при загрузке фото. Попробуйте ещё раз."))
        await state.clear()


@router.message(BotStates.waiting_for_photo, F.document)
async def handle_photo_as_document_step1(message: Message, state: FSMContext, bot: Bot):
    """Accept image sent as document (no compression) — same flow as photo."""
    telegram_id = str(message.from_user.id)
    doc = message.document
    if not doc:
        await message.answer(t("errors.try_later_short", "Ошибка. Попробуйте позже."))
        return
    ext = _document_image_ext(doc.mime_type, doc.file_name)
    if not ext:
        await message.answer(t("flow.only_images", "Поддерживаются только изображения: JPG, PNG, WEBP. Отправьте файл с фото."))
        return
    try:
        data_early = await state.get_data()
        audience = (data_early.get("audience_type") or "").strip().lower() or AUDIENCE_WOMEN
        if audience == AUDIENCE_MEN:
            await message.answer(
                t("audience.men_offramp", AUDIENCE_MEN_OFFRAMP_TEXT),
                reply_markup=main_menu_keyboard(),
            )
            await state.clear()
            return
        with get_db_session() as db:
            user_service = UserService(db)
            theme_service = ThemeService(db)
            trend_service = TrendService(db)
            u = message.from_user
            user_service.get_or_create_user(
                telegram_id,
                telegram_username=u.username,
                telegram_first_name=u.first_name,
                telegram_last_name=u.last_name,
            )
            theme_ids_with_trends = trend_service.list_theme_ids_with_active_trends(audience)
            all_themes = theme_service.list_all()
            themes = [t for t in all_themes if t.enabled and t.id in theme_ids_with_trends]
            themes_data = [{"id": t.id, "name": t.name, "emoji": t.emoji or ""} for t in themes]
            file = await bot.get_file(doc.file_id)
            inputs_dir = os.path.join(settings.storage_base_path, "inputs")
            os.makedirs(inputs_dir, exist_ok=True)
            local_path = os.path.join(inputs_dir, f"{doc.file_id}{ext}")
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
        await state.update_data(
            photo_file_id=doc.file_id,
            photo_local_path=local_path,
        )
        data = await state.get_data()
        pre_selected_id = data.get("selected_trend_id")
        if pre_selected_id and pre_selected_id != TREND_CUSTOM_ID:
            with get_db_session() as db:
                trend = TrendService(db).get(pre_selected_id)
                if trend and trend.enabled:
                    await state.set_state(BotStates.waiting_for_format)
                    await _try_delete_messages(bot, message.chat.id, data.get("last_bot_message_id"), message.message_id)
                    trend_name = trend.name
                    trend_emoji = trend.emoji or ""
                    example_path = _resolve_trend_example_path(getattr(trend, "example_image_path", None), str(trend.id))
                    if example_path:
                        try:
                            sent = await message.answer_photo(
                                photo=FSInputFile(example_path),
                                caption=(
                                    f"✅ Фото принято. Тренд: {trend_emoji} {trend_name}\n\n"
                                    "Выберите формат кадра:"
                                ),
                                reply_markup=format_keyboard(),
                            )
                        except Exception:
                            sent = await message.answer(
                                f"✅ Фото принято. Тренд: {trend_emoji} {trend_name}\n\nВыберите формат кадра:",
                                reply_markup=format_keyboard(),
                            )
                    else:
                        sent = await message.answer(
                            f"✅ Фото принято. Тренд: {trend_emoji} {trend_name}\n\nВыберите формат кадра:",
                            reply_markup=format_keyboard(),
                        )
                    await state.update_data(last_bot_message_id=sent.message_id)
                    logger.info("photo_received_as_document_deeplink", extra={"user_id": telegram_id, "trend_id": pre_selected_id})
                    return
        await state.set_state(BotStates.waiting_for_trend)
        await _try_delete_messages(bot, message.chat.id, data.get("last_bot_message_id"), message.message_id)
        caption = t("flow.photo_accepted_choose_theme", "✅ Фото принято\n\nМы используем его, чтобы сохранить вашу внешность и стиль.\nВыберите тематику или придумайте свой образ 👇")
        sent = await message.answer(
            caption,
            reply_markup=themes_keyboard(themes_data),
        )
        await state.update_data(last_bot_message_id=sent.message_id)
        logger.info("photo_received_as_document", extra={"user_id": telegram_id})
    except Exception:
        logger.exception("Error in handle_photo_as_document_step1", extra={"user_id": telegram_id})
        await message.answer(t("errors.upload_file", "Ошибка при загрузке файла. Попробуйте ещё раз."))
        await state.clear()


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


@router.callback_query(F.data.startswith(THEME_CB_PREFIX))
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
        await callback.message.edit_text(caption, reply_markup=kb)
        await state.update_data(current_theme_id=theme_id, current_theme_page=page)
        await callback.answer()
    except Exception as e:
        logger.exception("Error in select_theme_or_theme_page: %s", e)
        await callback.answer(t("errors.try_later_short", "Ошибка. Попробуйте позже."), show_alert=True)


@router.callback_query(F.data == NAV_THEMES)
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
        await state.update_data(current_theme_id=None, current_theme_page=None)
        caption = t("flow.photo_accepted_choose_theme", "✅ Фото принято\n\nВыберите тематику или придумайте свой образ 👇")
        await callback.message.edit_text(caption, reply_markup=themes_keyboard(themes_data))
        await callback.answer()
    except Exception as e:
        logger.exception("Error in nav_back_to_themes: %s", e)
        await callback.answer(t("errors.try_later_short", "Ошибка. Попробуйте позже."), show_alert=True)


# --- Step 2: Trend selected or "Своя идея" ---
@router.callback_query(F.data.startswith("trend:"))
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
            await state.set_state(BotStates.waiting_for_format)

            audit.log(
                actor_type="user",
                actor_id=telegram_id,
                action="trend_selected",
                entity_type="trend",
                entity_id=trend_id,
                payload={},
            )

        if example_path:
            try:
                photo = FSInputFile(example_path)
                sent = await callback.message.answer_photo(
                    photo=photo,
                    caption=(
                        f"✅ Тренд: {trend_emoji} {trend_name}\n\n"
                        "Пример результата 👇\nВыберите формат кадра:"
                    ),
                    reply_markup=format_keyboard(),
                )
            except Exception as e:
                logger.warning("Failed to send trend example photo, falling back to text: %s", e)
                sent = await callback.message.answer(
                    f"✅ Тренд: {trend_emoji} {trend_name}\n\n"
                    "Выберите формат кадра:",
                    reply_markup=format_keyboard(),
                )
        else:
            sent = await callback.message.answer(
                f"✅ Тренд: {trend_emoji} {trend_name}\n\n"
                "Выберите формат кадра:",
                reply_markup=format_keyboard(),
            )
        await state.update_data(last_bot_message_id=sent.message_id)
        await callback.answer()
    except Exception:
        logger.exception("Error in select_trend_or_idea")
        await callback.answer(t("errors.try_later_short", "Ошибка. Попробуйте позже."), show_alert=True)


# --- Step 2b: Custom prompt (for "Своя идея") ---
@router.message(BotStates.waiting_for_prompt, F.text)
async def handle_custom_prompt(message: Message, state: FSMContext, bot: Bot):
    """Receive user's custom prompt for 'Своя идея'."""
    prompt = (message.text or "").strip()
    if len(prompt) < 3:
        await message.answer(t("errors.idea_min_length", "Опишите идею подробнее (минимум 3 символа)."))
        return
    if len(prompt) > 2000:
        await message.answer(t("errors.idea_max_length", "Текст слишком длинный. Сократите до 2000 символов."))
        return
    
    data = await state.get_data()
    await _try_delete_messages(bot, message.chat.id, data.get("last_bot_message_id"), message.message_id)
    await state.update_data(custom_prompt=prompt)
    await state.set_state(BotStates.waiting_for_format)
    sent = await message.answer(
        f"✅ Идея сохранена!\n\n"
        f"Выберите формат кадра:",
        reply_markup=format_keyboard(),
    )
    await state.update_data(last_bot_message_id=sent.message_id)


# --- Назад к трендам / В меню (с экрана выбора формата) ---
@router.callback_query(F.data == "nav:trends")
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
        caption = t("flow.photo_accepted_choose_theme", "Выберите тематику или придумайте свой образ 👇")
        await callback.message.answer(
            caption,
            reply_markup=themes_keyboard(themes_data),
        )
        await callback.answer()
    except Exception:
        logger.exception("Error in nav_back_to_trends")
        await callback.answer(t("errors.try_later_short", "Ошибка. Попробуйте позже."), show_alert=True)


@router.callback_query(F.data == "nav:menu")
async def nav_back_to_menu(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Вернуться в главное меню."""
    await state.clear()
    await _try_delete_messages(bot, callback.message.chat.id, callback.message.message_id)
    await callback.message.answer(
        "Главное меню. Загрузите фото, чтобы начать.",
        reply_markup=main_menu_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "nav:profile")
async def nav_profile(callback: CallbackQuery):
    """Открыть «Мой профиль» (баланс) по кнопке после 4K или из меню."""
    telegram_id = str(callback.from_user.id)
    try:
        with get_db_session() as db:
            user_service = UserService(db)
            sec_svc = SecuritySettingsService(db)
            session_svc = SessionService(db)
            hd_svc = HDBalanceService(db)
            user = user_service.get_by_telegram_id(telegram_id)
            if not user:
                user = user_service.get_or_create_user(
                    telegram_id,
                    telegram_username=callback.from_user.username,
                    telegram_first_name=callback.from_user.first_name,
                    telegram_last_name=callback.from_user.last_name,
                )
            sec = sec_svc.get_or_create()
            free_limit = getattr(sec, "free_generations_per_user", 3)
            free_used = getattr(user, "free_generations_used", 0)
            free_left = max(0, free_limit - free_used)
            copy_limit = getattr(sec, "copy_generations_per_user", 1)
            copy_used = getattr(user, "copy_generations_used", 0)
            copy_left = max(0, copy_limit - copy_used)
            token_balance = user.token_balance
            total_purchased = getattr(user, "total_purchased", 0)
            hd_credits = getattr(user, "hd_credits_balance", 0)
            show_referral = getattr(user, "has_purchased_hd", False)

            active_session = session_svc.get_active_session(user.id)
            plan_name = None
            remaining_takes = 0
            total_takes = 0
            hd_balance_total = 0
            if active_session:
                _pack = db.query(Pack).filter(Pack.id == active_session.pack_id).one_or_none()
                plan_name = _pack.name if _pack else active_session.pack_id
                remaining_takes = active_session.takes_limit - active_session.takes_used
                total_takes = active_session.takes_limit
                hd_balance_total = hd_svc.get_balance(user)["total"]

        text = t("profile.title", "👤 *Мой профиль*") + "\n\n"
        if plan_name:
            plan_safe = _escape_markdown(str(plan_name))
            text += (
                f"📦 *Текущий план:* {plan_safe}\n"
                f"📸 *Осталось снимков:* {remaining_takes} из {total_takes}\n"
                f"🖼 *4K без watermark:* {hd_balance_total}\n\n"
            )
        else:
            text += "📦 *Текущий план:* Нет активного плана\n\n"
        text += tr(
            "profile.body",
            "🆓 *Бесплатные превью:* {free_left} из {free_limit}\n"
            "🔄 *«Сделать такую же»:* {copy_left} из {copy_limit}\n"
            "💰 *Баланс генераций:* {token_balance}\n"
            "📊 *Всего куплено:* {total_purchased}\n\n"
            "Бесплатные генерации дают превью с watermark.\n"
            "Купите пакет — получайте фото в полном качестве!",
            free_left=free_left,
            free_limit=free_limit,
            copy_left=copy_left,
            copy_limit=copy_limit,
            token_balance=token_balance,
            total_purchased=total_purchased,
        )
        if hd_credits > 0:
            text += f"\n\n🎁 *Бонусы 4K:* {hd_credits}"

        buttons = [
            [InlineKeyboardButton(text=t("profile.btn.top_up", "🛒 Выбрать фотосессию"), callback_data="shop:open")],
        ]
        if show_referral:
            buttons.append([
                InlineKeyboardButton(text="💌 Пригласить подругу", callback_data="referral:invite"),
                InlineKeyboardButton(text="📊 Реферальный баланс", callback_data="referral:status"),
            ])
        profile_kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=profile_kb)
        await callback.answer()
    except Exception:
        logger.exception("Error in nav_profile")
        await callback.answer(t("errors.profile_load", "Ошибка загрузки профиля."), show_alert=True)


# --- Step 3: Format selected, create job and generate ---
@router.callback_query(F.data.startswith("format:"))
async def select_format_and_generate(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Format selected — create job and start generation."""
    telegram_id = str(callback.from_user.id)
    format_key = callback.data.split(":", 1)[1]
    
    if format_key not in IMAGE_FORMATS:
        await callback.answer(t("errors.unknown_format", "Неизвестный формат"), show_alert=True)
        return
    
    data = await state.get_data()
    photo_file_id = data.get("photo_file_id")
    photo_local_path = data.get("photo_local_path")
    copy_photos_received = data.get("copy_photos_received") or []
    reference_path = data.get("reference_path")  # флоу «Сделать такую же»: референс стиля (1-е фото)
    trend_id = data.get("selected_trend_id")
    trend_name = data.get("selected_trend_name", "")
    custom_prompt = data.get("custom_prompt")

    if copy_photos_received and len(copy_photos_received) == 2:
        # 1 = стиль (референс), 2 = лицо девушки, 3 = лицо парня — все три улетают в Gemini
        if reference_path and os.path.exists(reference_path):
            input_file_ids = ["ref"] + [p["file_id"] for p in copy_photos_received]
            input_local_paths = [reference_path] + [p["path"] for p in copy_photos_received]
        else:
            input_file_ids = [p["file_id"] for p in copy_photos_received]
            input_local_paths = [p["path"] for p in copy_photos_received]
    else:
        if not photo_file_id or not photo_local_path:
            await callback.answer(t("errors.session_expired_photo", "Сессия истекла. Начните заново: отправьте фото."), show_alert=True)
            await state.clear()
            return
        input_file_ids = [photo_file_id]
        input_local_paths = [photo_local_path]
    
    if not trend_id:
        await callback.answer(t("errors.choose_trend_or_idea", "Выберите тренд или введите свою идею."), show_alert=True)
        return
    
    if trend_id == TREND_CUSTOM_ID and not custom_prompt:
        await callback.answer(t("errors.enter_idea", "Введите описание своей идеи."), show_alert=True)
        return

    # Проверка размера файлов до потребления квоты/токенов
    for path in input_local_paths:
        if os.path.exists(path):
            size_mb = os.path.getsize(path) / (1024 * 1024)
            if size_mb > settings.max_file_size_mb:
                await callback.answer(
                    tr("errors.file_too_large_max", "Файл слишком большой ({size_mb:.1f} МБ). Максимум {max_mb} МБ.", size_mb=size_mb, max_mb=settings.max_file_size_mb),
                    show_alert=True,
                )
                return
    
    image_size = IMAGE_FORMATS[format_key]
    
    # Idempotency for job creation
    idempotency_key = f"job:{callback.message.chat.id}:{callback.message.message_id}:{format_key}"
    if not IdempotencyStore().check_and_set(idempotency_key):
        await callback.answer(t("errors.request_processing", "⏳ Запрос уже обрабатывается."))
        return
    
    try:
        with get_db_session() as db:
            user_service = UserService(db)
            trend_service = TrendService(db)
            take_svc = TakeService(db)
            session_svc = SessionService(db)
            audit = AuditService(db)

            user = user_service.get_or_create_user(
                telegram_id,
                telegram_username=callback.from_user.username,
                telegram_first_name=callback.from_user.first_name,
                telegram_last_name=callback.from_user.last_name,
            )

            if trend_id != TREND_CUSTOM_ID:
                trend = trend_service.get(trend_id)
                if not trend or not trend.enabled:
                    await callback.answer(t("errors.trend_unavailable", "Тренд недоступен."), show_alert=True)
                    return

            is_copy_flow = bool(data.get("copy_prompt"))
            take_type = "COPY" if is_copy_flow else ("CUSTOM" if trend_id == TREND_CUSTOM_ID else "TREND")
            copy_ref = data.get("reference_path") if is_copy_flow else None

            # Determine session context
            session = session_svc.get_active_session(user.id)
            session_id = None

            if getattr(user, "is_moderator", False):
                free_session = session_svc.create_free_preview_session(user.id)
                session_id = free_session.id
            elif session and session.pack_id != "free_preview":
                if not session_svc.can_take(session):
                    await callback.answer("📸 Лимит снимков исчерпан. Купите новый пакет.", show_alert=True)
                    return
                session_id = session.id
            elif (user.free_takes_used or 0) < 1:
                # Free take -- atomic increment to prevent race conditions
                from sqlalchemy import update as sa_update, func
                res = db.execute(
                    sa_update(User)
                    .where(User.id == user.id, (User.free_takes_used == None) | (User.free_takes_used < 1))
                    .values(free_takes_used=func.coalesce(User.free_takes_used, 0) + 1)
                )
                if res.rowcount == 0:
                    await callback.answer("Бесплатный снимок исчерпан. Купите пакет.", show_alert=True)
                    return
                db.flush()
                free_session = session_svc.create_free_preview_session(user.id)
                session_id = free_session.id
            else:
                # No free takes left, no active session — show paywall
                await callback.answer("Бесплатный снимок исчерпан. Купите пакет.", show_alert=True)
                return

            take = take_svc.create_take(
                user_id=user.id,
                trend_id=trend_id if trend_id != TREND_CUSTOM_ID else None,
                take_type=take_type,
                session_id=session_id,
                custom_prompt=custom_prompt,
                image_size=image_size,
                input_file_ids=input_file_ids,
                input_local_paths=input_local_paths,
                copy_reference_path=copy_ref,
            )
            created_take_id = take.id

            audience = (data.get("audience_type") or "").strip().lower() or AUDIENCE_WOMEN
            audit.log(
                actor_type="user",
                actor_id=telegram_id,
                action="take_started",
                entity_type="take",
                entity_id=created_take_id,
                payload={
                    "trend_id": trend_id,
                    "image_size": image_size,
                    "take_type": take_type,
                    "session_id": session_id,
                    "custom": bool(custom_prompt),
                    "audience": audience,
                },
            )

        from app.core.celery_app import celery_app

        await _try_delete_messages(bot, callback.message.chat.id, data.get("last_bot_message_id"), callback.message.message_id)
        progress_msg = await callback.message.answer(
            t("progress.take_step_1", "⏳ Генерация снимка [🟩⬜⬜] 1/3"),
        )

        celery_app.send_task(
            "app.workers.tasks.generate_take.generate_take",
            args=[created_take_id],
            kwargs={
                "status_chat_id": str(callback.message.chat.id),
                "status_message_id": progress_msg.message_id,
            },
        )

        await state.clear()
        await callback.answer("Генерация запущена!")
        logger.info("take_created", extra={"user_id": telegram_id, "take_id": created_take_id})
    except Exception:
        logger.exception("Error in select_format_and_generate", extra={"user_id": telegram_id})
        await callback.answer(t("errors.try_again", "Ошибка. Попробуйте ещё раз."), show_alert=True)
        await state.clear()


# --- Попробовать ещё раз: перегенерация с теми же параметрами ---
@router.callback_query(F.data.startswith("regenerate:"))
async def regenerate_same(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Перегенерация с теми же трендом, промптом и настройками (тот же флоу)."""
    telegram_id = str(callback.from_user.id)
    job_id = callback.data.split(":", 1)[1].strip()
    if not job_id:
        await callback.answer(t("errors.general_short", "Ошибка."), show_alert=True)
        return

    try:
        # Загружаем job и проверяем доступ (без долгого удержания сессии)
        with get_db_session() as db:
            job_service = JobService(db)
            job = job_service.get(job_id)
            user = db.query(User).filter(User.telegram_id == telegram_id).first()
            if not user:
                await callback.answer(t("errors.start_first", "Сначала нажмите /start."), show_alert=True)
                return
            if not job or str(job.user_id) != str(user.id):
                await callback.answer(t("errors.job_not_found", "Кадр не найден."), show_alert=True)
                return
            if job.status not in {"SUCCEEDED", "FAILED"}:
                await callback.answer(t("errors.wait_current_generation", "Подождите завершения текущей генерации."), show_alert=True)
                return
            file_ids = list(job.input_file_ids or [])
            if "ref" in file_ids:
                await callback.answer(
                    "Перегенерация для этого кадра недоступна. Загрузите фото заново через меню.",
                    show_alert=True,
                )
                return
            if not file_ids:
                await callback.answer(t("errors.no_source_photos", "Нет исходных фото для повтора."), show_alert=True)
                return
            trend_id = job.trend_id
            image_size = job.image_size or "1024x1024"
            custom_prompt = job.custom_prompt
            is_copy_flow = bool(job.used_copy_quota)

        # Скачиваем файлы по file_id (вне сессии БД)
        inputs_dir = os.path.join(settings.storage_base_path, "inputs")
        os.makedirs(inputs_dir, exist_ok=True)
        input_local_paths = []
        for i, fid in enumerate(file_ids):
            try:
                file = await bot.get_file(fid)
                ext = (os.path.splitext(file.file_path or "")[1]) or ".jpg"
                local_path = os.path.join(inputs_dir, f"regen_{job_id}_{i}_{fid[:16]}{ext}")
                await bot.download_file(file.file_path, local_path)
                if os.path.getsize(local_path) / (1024 * 1024) > settings.max_file_size_mb:
                    for p in input_local_paths:
                        try:
                            os.remove(p)
                        except OSError:
                            pass
                    await callback.answer(
                        tr("errors.file_too_large_max_only", "Файл слишком большой. Максимум {max_mb} МБ.", max_mb=settings.max_file_size_mb),
                        show_alert=True,
                    )
                    return
                input_local_paths.append(local_path)
            except Exception as e:
                logger.warning("regenerate_download_failed", extra={"file_id": fid, "error": str(e)})
                for p in input_local_paths:
                    try:
                        os.remove(p)
                    except OSError:
                        pass
                await callback.answer(
                    "Не удалось загрузить фото. Попробуйте заново через меню.",
                    show_alert=True,
                )
                return

        # Квота, создание джоба, отправка в воркер
        with get_db_session() as db:
            user_service = UserService(db)
            trend_service = TrendService(db)
            job_service = JobService(db)
            audit = AuditService(db)
            user = user_service.get_by_telegram_id(telegram_id)
            if not user:
                await callback.answer(t("errors.start_again", "Ошибка. Нажмите /start."), show_alert=True)
                return
            if trend_id != TREND_CUSTOM_ID:
                trend = trend_service.get(trend_id)
                if not trend or not trend.enabled:
                    await callback.answer(t("errors.trend_no_longer", "Тренд больше недоступен."), show_alert=True)
                    return

            used_free_quota = False
            used_copy_quota = False
            if is_copy_flow:
                used_copy_quota = user_service.try_use_copy_generation(user)
                db.refresh(user)
            else:
                used_free_quota = user_service.try_use_free_generation(user)
                db.refresh(user)

            if not used_free_quota and not used_copy_quota:
                if not user_service.can_reserve(user, settings.generation_cost_tokens):
                    sec = SecuritySettingsService(db).get_or_create()
                    if is_copy_flow:
                        limit = getattr(sec, "copy_generations_per_user", 1)
                        msg = f"Бесплатная генерация «Сделать такую же» ({limit}/аккаунт) исчерпана. Пополните баланс."
                    else:
                        limit = getattr(sec, "free_generations_per_user", 3)
                        msg = f"Бесплатные генерации ({limit}/аккаунт) исчерпаны. Пополните баланс токенов."
                    await callback.answer(msg, show_alert=True)
                    return
                new_job_id = str(uuid4())
                if not user_service.hold_tokens(user, new_job_id, settings.generation_cost_tokens):
                    await callback.answer(t("errors.reserve_tokens_failed", "Не удалось зарезервировать токены."), show_alert=True)
                    return
            else:
                new_job_id = None

            reserved_for_job = 0 if (used_free_quota or used_copy_quota) else settings.generation_cost_tokens
            new_job = job_service.create_job(
                user_id=user.id,
                trend_id=trend_id,
                input_file_ids=file_ids,
                input_local_paths=input_local_paths,
                reserved_tokens=reserved_for_job,
                used_free_quota=used_free_quota,
                used_copy_quota=used_copy_quota,
                job_id=new_job_id,
                custom_prompt=custom_prompt,
                image_size=image_size,
            )
            created_job_id = new_job.job_id
            audit.log(
                actor_type="user",
                actor_id=telegram_id,
                action="job_created",
                entity_type="job",
                entity_id=created_job_id,
                payload={
                    "trend_id": trend_id,
                    "image_size": image_size,
                    "regenerate_of": job_id,
                },
            )

        from app.core.celery_app import celery_app

        progress_msg = await callback.message.answer(
            "⏳ Перегенерация с теми же настройками...",
        )
        celery_app.send_task(
            "app.workers.tasks.generation_v2.generate_image",
            args=[created_job_id],
            kwargs={
                "status_chat_id": str(callback.message.chat.id),
                "status_message_id": progress_msg.message_id,
            },
        )
        await state.clear()
        await callback.answer(t("errors.regenerate_launched", "Генерация запущена!"))
        logger.info("job_regenerate", extra={"user_id": telegram_id, "job_id": created_job_id, "regenerate_of": job_id})
    except Exception:
        logger.exception("Error in regenerate_same", extra={"user_id": telegram_id, "job_id": job_id})
        await callback.answer(t("errors.try_again", "Ошибка. Попробуйте ещё раз."), show_alert=True)


# ===========================================
# Магазин — покупка пакетов генераций за Stars
# ===========================================

@router.message(lambda m: (m.text or "").strip() == t("menu.btn.shop", "🛒 Купить тариф"))
async def shop_menu_text(message: Message):
    """Открыть магазин по нажатию кнопки в меню."""
    await _show_shop(message)


@router.callback_query(F.data == "shop:open")
async def shop_menu_callback(callback: CallbackQuery):
    """Открыть магазин по нажатию инлайн-кнопки."""
    await _show_shop(callback.message, edit=False)
    await callback.answer()


async def _show_shop(message: Message, edit: bool = False):
    """Экран «Выбор фотосессии» — баланс + тарифы (Avatar → Dating → Creator → Trial). Outcome-first."""
    try:
        telegram_id = str(message.from_user.id) if message.from_user else ""
        with get_db_session() as db:
            payment_service = PaymentService(db)
            payment_service.seed_default_packs()
            db.commit()
            text, kb_dict = build_balance_tariffs_message(db, telegram_id)

        if kb_dict is None:
            await message.answer(t("shop.unavailable", "Тарифы временно недоступны."), reply_markup=main_menu_keyboard())
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


@router.callback_query(F.data.startswith("buy:"))
async def buy_pack(callback: CallbackQuery, bot: Bot):
    """Пользователь выбрал пакет — отправляем invoice."""
    pack_id = callback.data.split(":", 1)[1]
    telegram_id = str(callback.from_user.id)

    try:
        with get_db_session() as db:
            payment_service = PaymentService(db)
            user_service = UserService(db)

            user = user_service.get_or_create_user(
                telegram_id,
                telegram_username=callback.from_user.username,
                telegram_first_name=callback.from_user.first_name,
                telegram_last_name=callback.from_user.last_name,
            )
            pack = payment_service.get_pack(pack_id)
            if not pack or not pack.enabled:
                await callback.answer(t("pay.pack_unavailable", "Пакет недоступен."), show_alert=True)
                return

            payload = payment_service.build_payload(pack.id, user.id)
            pack_title = f"{pack.emoji} {pack.name}"
            pack_desc = f"{pack.tokens} генераций без watermark. {pack.description}"
            pack_label = pack.name
            pack_stars = pack.stars_price

        await bot.send_invoice(
            chat_id=callback.message.chat.id,
            title=pack_title,
            description=pack_desc,
            payload=payload,
            currency="XTR",
            prices=[LabeledPrice(label=pack_label, amount=pack_stars)],
        )
        await callback.answer()
    except Exception:
        logger.exception("Error in buy_pack")
        await callback.answer(t("pay.create_error", "Ошибка при создании платежа."), show_alert=True)


# ===========================================
# Разблокировка фото (unlock) — за токены или за Stars
# ===========================================

@router.callback_query(F.data.startswith("unlock_tokens:"))
async def unlock_photo_with_tokens(callback: CallbackQuery, bot: Bot):
    """Разблокировать фото с watermark за токены из баланса (без Stars)."""
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
                await callback.answer("Недостаточно токенов. Используйте оплату Stars.", show_alert=True)
                return

            # Записать в payments для единой аналитики (pack_id=unlock_tokens)
            payment_service.record_unlock_tokens(user.id, job_id, unlock_cost)

            # Отправить оригинал без watermark; обновить job (источник истины оплаты)
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
                caption=t("success.unlock_caption", "🔓 Фото разблокировано! Вот ваш кадр в полном качестве (без сжатия)."),
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
            await callback.answer("Файл не найден. Обратитесь в /paysupport.", show_alert=True)
        logger.info("unlock_with_tokens", extra={"user_id": telegram_id, "job_id": job_id})
    except Exception:
        logger.exception("Error in unlock_photo_with_tokens")
        await callback.answer(t("errors.try_later_short", "Ошибка. Попробуйте позже."), show_alert=True)


@router.callback_query(F.data.startswith("unlock_hd:"))
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
                caption="🎁 Фото разблокировано за бонус 4K! Вот ваш кадр в полном качестве.",
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
            await callback.answer("Файл не найден. Обратитесь в /paysupport.", show_alert=True)
        logger.info("unlock_with_hd_credits", extra={"user_id": telegram_id, "job_id": job_id})
    except Exception:
        logger.exception("Error in unlock_photo_with_hd_credits")
        await callback.answer("Ошибка. Попробуйте позже.", show_alert=True)


@router.callback_query(F.data.startswith("unlock:"))
async def unlock_photo(callback: CallbackQuery, bot: Bot):
    """Разблокировать фото с watermark — отправить invoice на unlock_cost_stars."""
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

            payload = payment_service.build_payload("unlock", user.id, job_id=job_id)

        cost = settings.unlock_cost_stars
        rate = getattr(settings, "star_to_rub", 1.3)
        cost_str = format_stars_rub(cost, rate)
        await bot.send_invoice(
            chat_id=callback.message.chat.id,
            title=t("unlock.invoice_title", "🔓 Разблокировать фото"),
            description=tr("unlock.invoice_description", "Получить фото без watermark в полном качестве ({cost})", cost=cost_str),
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

@router.pre_checkout_query()
async def handle_pre_checkout(pre_checkout: PreCheckoutQuery, bot: Bot):
    """Валидация платежа перед списанием Stars."""
    telegram_id = str(pre_checkout.from_user.id)
    payload = pre_checkout.invoice_payload

    try:
        with get_db_session() as db:
            payment_service = PaymentService(db)
            ok, error_msg = payment_service.validate_pre_checkout(payload, telegram_id)

        if ok:
            await bot.answer_pre_checkout_query(pre_checkout.id, ok=True)
            logger.info("pre_checkout_approved", extra={"user": telegram_id, "payload": payload})
        else:
            await bot.answer_pre_checkout_query(
                pre_checkout.id, ok=False, error_message=error_msg
            )
            logger.warning(
                "pre_checkout_rejected",
                extra={"user": telegram_id, "payload": payload, "reason": error_msg},
            )
    except Exception:
        logger.exception("Error in pre_checkout")
        await bot.answer_pre_checkout_query(
            pre_checkout.id, ok=False, error_message="Внутренняя ошибка. Попробуйте позже."
        )


@router.message(F.successful_payment)
async def handle_successful_payment(message: Message, state: FSMContext, bot: Bot):
    """Обработка успешного платежа — начисление токенов."""
    payment_info = message.successful_payment
    telegram_id = str(message.from_user.id)
    payload = payment_info.invoice_payload
    charge_id = payment_info.telegram_payment_charge_id
    provider_charge_id = payment_info.provider_payment_charge_id

    try:
        # Handle session-based payloads first
        if payload.startswith("session:") or payload.startswith("upgrade:"):
            with get_db_session() as db:
                payment_service = PaymentService(db)
                audit = AuditService(db)

                if payload.startswith("session:"):
                    pack_id = payload.split(":", 1)[1]
                    payment_obj, session = payment_service.process_session_purchase(
                        telegram_user_id=telegram_id,
                        telegram_payment_charge_id=charge_id,
                        provider_payment_charge_id=provider_charge_id,
                        pack_id=pack_id,
                        stars_amount=payment_info.total_amount,
                        payload=payload,
                    )
                    if payment_obj and session:
                        pack = payment_service.get_pack(pack_id)
                        hd_svc = HDBalanceService(db)
                        user = db.query(User).filter(User.telegram_id == telegram_id).one_or_none()
                        balance = hd_svc.get_balance(user) if user else {"total": 0}
                        is_collection = getattr(pack, "pack_subtype", "standalone") == "collection" and pack.playlist

                        audit.log(
                            actor_type="user",
                            actor_id=telegram_id,
                            action="pay_success",
                            entity_type="payment",
                            entity_id=charge_id,
                            payload={"pack_id": pack_id, "session_id": session.id, "stars": payment_info.total_amount},
                        )

                        remaining = session.takes_limit - session.takes_used
                        if is_collection:
                            await state.set_state(BotStates.waiting_for_photo)
                            await message.answer(
                                f"✅ Коллекция {pack.emoji} {pack.name} активирована!\n\n"
                                f"Отправьте одно фото — по нему будут созданы все образы коллекции.",
                                reply_markup=main_menu_keyboard(),
                            )
                        else:
                            await message.answer(
                                f"✅ Пакет {pack.emoji} {pack.name} активирован!\n\n"
                                f"Снимков: {remaining}\n"
                                f"4K без watermark: {balance['total']}\n\n"
                                f"Отправьте фото для первого снимка!",
                                reply_markup=main_menu_keyboard(),
                            )
                    elif payment_obj:
                        await message.answer("✅ Платёж уже обработан.")
                    else:
                        await message.answer("⚠️ Ошибка обработки. Обратитесь в /paysupport.")

                elif payload.startswith("upgrade:"):
                    parts = payload.split(":")
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

                        remaining = new_session.takes_limit - new_session.takes_used
                        await message.answer(
                            f"⬆️ Апгрейд до {pack.emoji} {pack.name}!\n\n"
                            f"Снимков: {remaining}\n"
                            f"4K без watermark: {balance['total']}\n\n"
                            f"Продолжайте съёмку!",
                            reply_markup=main_menu_keyboard(),
                        )
                    elif payment_obj:
                        await message.answer("✅ Платёж уже обработан.")
                    else:
                        await message.answer("⚠️ Ошибка обработки. Обратитесь в /paysupport.")

            return

        # Legacy token-based flow
        with get_db_session() as db:
            payment_service = PaymentService(db)
            full_payload = payment_service.resolve_payload(payload)
            parsed = PaymentService.parse_payload(full_payload)
        pack_id = parsed.get("pack_id", "")
        job_id_unlock = parsed.get("job_id")

        if not pack_id and not job_id_unlock:
            logger.warning("successful_payment_invalid_payload", extra={"telegram_id": telegram_id, "charge_id": charge_id})
            await message.answer(t("payment.unknown_order", "Не удалось определить заказ по платежу. Напишите в /paysupport и укажите время платежа — разберём вручную."))
            return

        with get_db_session() as db:
            payment_service = PaymentService(db)
            user_service = UserService(db)
            audit = AuditService(db)

            if pack_id == "unlock":
                # Разблокировка фото
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
                if payment and job_id_unlock:
                    # Отправить оригинал без watermark; owner check
                    user = user_service.get_by_telegram_id(telegram_id)
                    job = db.query(Job).filter(Job.job_id == job_id_unlock).one_or_none()
                    if job and user and job.user_id != user.id:
                        logger.warning("unlock_payment_owner_mismatch", extra={"job_id": job_id_unlock, "telegram_id": telegram_id})
                    if job and job.output_path_original and user and job.user_id == user.id:
                        preview_created_at = job.updated_at
                        from app.services.telegram.client import TelegramClient
                        tg = TelegramClient()
                        try:
                            tg.send_document(
                                user.telegram_id,
                                job.output_path_original,
                                caption=t("success.unlock_caption", "🔓 Фото разблокировано! Вот ваш кадр в полном качестве (без сжатия)."),
                                reply_markup={
                                    "inline_keyboard": [
                                        [
                                            {"text": t("success.btn.menu", "📋 В меню"), "callback_data": "success_action:menu"},
                                            {"text": t("success.btn.more", "🔄 Сделать ещё"), "callback_data": "success_action:more"},
                                        ]
                                    ]
                                },
                            )
                            job.is_preview = False
                            job.unlocked_at = datetime.now(timezone.utc)
                            job.unlock_method = "stars"
                            db.add(job)
                            latency = (datetime.now(timezone.utc) - preview_created_at).total_seconds() if preview_created_at else None
                            paywall_record_unlock(
                                job_id=job_id_unlock,
                                user_id=user.id,
                                method="stars",
                                price_stars=cost,
                                price_tokens=0,
                                pack_id="unlock",
                                receipt_id=charge_id,
                                preview_to_pay_latency_seconds=latency,
                            )
                        finally:
                            tg.close()
                    elif user:
                        await message.answer(t("payment.unlock_send_error", "Оплата прошла, но не удалось отправить фото. Напишите в /paysupport с описанием — мы вышлем кадр вручную."))

                audit.log(
                    actor_type="user",
                    actor_id=telegram_id,
                    action="payment_unlock",
                    entity_type="payment",
                    entity_id=charge_id,
                    payload={"job_id": job_id_unlock, "stars": cost},
                )
                logger.info(
                    "unlock_payment_completed",
                    extra={"user": telegram_id, "job_id": job_id_unlock, "charge_id": charge_id},
                )
            else:
                # Покупка пакета генераций
                pack = payment_service.get_pack(pack_id)
                if not pack:
                    logger.error("payment_pack_not_found", extra={"pack_id": pack_id})
                    await message.answer(t("payment.pack_not_found", "Ошибка: пакет не найден. Обратитесь в /paysupport."))
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
                            "✅ Пакет *{emoji} {name}* активирован!\n\nНачислено: *{tokens}* генераций\nВаш баланс: *{balance}* генераций\n\nТеперь ваши фото будут без watermark!",
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

                    if user and payment and getattr(user, "referred_by_user_id", None):
                        try:
                            ref_svc = ReferralService(db)
                            referrer = db.query(User).filter(User.id == user.referred_by_user_id).one_or_none()
                            if referrer:
                                bonus = ref_svc.create_bonus(referrer, user, payment)
                                if bonus:
                                    audit.log(
                                        actor_type="system",
                                        actor_id="referral",
                                        action="referral_first_pay_success",
                                        entity_type="payment",
                                        entity_id=payment.id,
                                        payload={
                                            "referrer_id": referrer.id,
                                            "referral_id": user.id,
                                            "pack_stars": pack.stars_price,
                                            "bonus_credits": bonus.hd_credits_amount,
                                        },
                                    )
                                    audit.log(
                                        actor_type="system",
                                        actor_id="referral",
                                        action="referral_bonus_pending",
                                        entity_type="referral_bonus",
                                        entity_id=bonus.id,
                                        payload={"referrer_id": referrer.id, "credits": bonus.hd_credits_amount},
                                    )
                                    referrer_tg_id = referrer.telegram_id
                                    bonus_credits = bonus.hd_credits_amount
                                    try:
                                        from app.services.telegram.client import TelegramClient as TgClient
                                        tg_notify = TgClient()
                                        try:
                                            tg_notify.send_message(
                                                referrer_tg_id,
                                                f"🎉 Подруга купила пакет! Твой бонус ({bonus_credits} 4K) в обработке.\n"
                                                f"Будет доступен через 12–24 часа.",
                                            )
                                        finally:
                                            tg_notify.close()
                                    except Exception:
                                        logger.exception("referral_pending_notify_fail")
                        except Exception:
                            logger.exception("referral_bonus_creation_error")

                else:
                    await message.answer(
                        t("payment.credit_error", "⚠️ Оплата получена, но произошла ошибка начисления.\nОбратитесь в /paysupport — мы решим вопрос."),
                        reply_markup=main_menu_keyboard(),
                    )
    except Exception:
        logger.exception("Error in successful_payment", extra={"charge_id": charge_id})
        await message.answer(
            t("payment.generic_error", "⚠️ Произошла ошибка при обработке платежа.\nОбратитесь в /paysupport."),
            reply_markup=main_menu_keyboard(),
        )


# ===========================================
# Команды поддержки платежей (требование Telegram)
# ===========================================

@router.message(Command("paysupport"))
async def cmd_paysupport(message: Message):
    """Поддержка по платежам (требование Telegram для ботов с оплатой)."""
    try:
        await message.answer(
            t(
                "cmd.paysupport",
                "💬 *Поддержка по платежам*\n\n"
                "Если у вас возникли проблемы с оплатой или начислением генераций:\n\n"
                "1. Убедитесь, что у вас достаточно Telegram Stars\n"
                "2. Проверьте баланс в «👤 Мой профиль»\n"
                "3. Напишите нам в чат поддержки\n\n"
                "Мы обработаем ваш запрос в кратчайшие сроки.\n\n"
                "⚠️ Telegram support не рассматривает вопросы по покупкам в ботах.",
            ),
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
    except Exception:
        logger.exception("Error in cmd_paysupport")
        await message.answer(t("errors.try_later", "Произошла ошибка. Попробуйте позже."))


@router.message(Command("terms"))
async def cmd_terms(message: Message):
    """Условия использования (требование Telegram для ботов с оплатой)."""
    try:
        await message.answer(
            t(
                "cmd.terms",
                "📄 *Условия использования NanoBanan*\n\n"
                "1. Генерации приобретаются за Telegram Stars.\n"
                "2. Бесплатные генерации дают результат с watermark (превью).\n"
                "3. Оплаченные генерации дают полное качество без watermark.\n"
                "4. Возврат Stars возможен до использования генераций.\n"
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


# ===========================================
# Обработка после генерации (успех / ошибка)
# ===========================================

@router.callback_query(
    F.data.in_({"error_action:menu", "error_action:retry", "success_action:menu", "success_action:more"})
)
async def handle_error_recovery(callback: CallbackQuery, state: FSMContext):
    """После генерации (успех или ошибка): вернуться в меню или сгенерировать ещё."""
    await state.clear()
    action = callback.data.split(":", 1)[-1]  # menu, retry или more
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


@router.callback_query(F.data == "error_action:replace_photo")
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


@router.callback_query(F.data.startswith("error_action:choose_trend:"))
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


# ===========================================
# Оплата переводом на карту (bank transfer flow)
# ===========================================

@router.callback_query(F.data == "bank_transfer:start")
async def bank_transfer_start(callback: CallbackQuery, state: FSMContext):
    """Шаг 1: описание оплаты переводом + 3 кнопки тарифов (тексты и включение из БД)."""
    try:
        with get_db_session() as db:
            bank_svc = BankTransferSettingsService(db)
            effective = bank_svc.get_effective()
            if not effective["enabled"]:
                await callback.answer("Оплата переводом временно недоступна.", show_alert=True)
                return
            payment_service = PaymentService(db)
            packs = payment_service.list_product_ladder_packs()
            packs_data = [
                {"id": p.id, "name": p.name, "emoji": p.emoji, "tokens": getattr(p, "tokens", 0), "stars_price": p.stars_price, "outcome": _pack_outcome_label(p)}
                for p in packs
            ]
            step1_text = effective["step1_description"]

        if not packs_data:
            await callback.answer("Пакеты недоступны.", show_alert=True)
            return

        rate = getattr(settings, "star_to_rub", 1.3)
        text = step1_text
        buttons = []
        for pack in packs_data:
            rub = round(pack["stars_price"] * rate)
            outcome = pack.get("outcome", "")
            label = f"{pack['emoji']} {pack['name']}: {outcome} — {pack['stars_price']}⭐ ({rub} ₽)" if outcome else f"{pack['emoji']} {pack['name']} — {pack['stars_price']}⭐ ({rub} ₽)"
            buttons.append([InlineKeyboardButton(text=label, callback_data=f"bank_pack:{pack['id']}")])
        buttons.append([InlineKeyboardButton(text=t("nav.btn.menu", "📋 В меню"), callback_data="nav:menu")])

        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)
        await callback.answer()
    except Exception:
        logger.exception("bank_transfer_start error")
        await callback.answer("Ошибка. Попробуйте позже.", show_alert=True)


def _generate_receipt_code() -> str:
    """Сгенерировать уникальный номер «оплата № N» через Redis-счётчик."""
    try:
        num = redis_client.incr("bank_transfer:receipt_code_seq")
    except Exception:
        import random
        num = random.randint(1000, 999999)
    return f"оплата № {num}"


@router.callback_query(F.data.startswith("bank_pack:"))
async def bank_pack_selected(callback: CallbackQuery, state: FSMContext):
    """Шаг 2: пользователь выбрал тариф — показываем реквизиты и ждём чек (из БД)."""
    pack_id = callback.data.split(":", 1)[1]
    if pack_id not in PRODUCT_LADDER_IDS:
        await callback.answer("Пакет недоступен.", show_alert=True)
        return
    try:
        with get_db_session() as db:
            payment_service = PaymentService(db)
            bank_svc = BankTransferSettingsService(db)
            effective = bank_svc.get_effective()
            pack = payment_service.get_pack(pack_id)
            if not pack or not pack.enabled:
                await callback.answer("Пакет недоступен.", show_alert=True)
                return
            pack_name = f"{pack.emoji} {pack.name}"
            tokens = pack.tokens
            stars_price = pack.stars_price

        rate = getattr(settings, "star_to_rub", 1.3)
        expected_rub = round(stars_price * rate)

        receipt_code = _generate_receipt_code()

        await state.update_data(
            bank_pack_id=pack_id,
            bank_pack_name=pack_name,
            bank_tokens=tokens,
            bank_stars=stars_price,
            bank_expected_rub=expected_rub,
            bank_receipt_code=receipt_code,
            bank_receipt_attempts=0,
        )
        await state.set_state(BotStates.bank_transfer_waiting_receipt)

        card = effective["card_number"]
        comment = effective["comment"]
        comment_line = f"💬 Комментарий: {comment}\n" if comment else ""
        step2_tpl = effective["step2_requisites"]
        text = step2_tpl.format(
            pack_name=pack_name,
            tokens=tokens,
            expected_rub=expected_rub,
            card=card,
            comment_line=comment_line,
            receipt_code=receipt_code,
        )
        if BANK_RECEIPT_COMMENT_DISABLED:
            import re as _re
            text = _re.sub(r"\n?📝 В комментарии к переводу укажите:[^\n]*\n?", "\n", text)
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="bank_transfer:cancel")],
        ])
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=cancel_kb)
        await callback.answer()
    except Exception:
        logger.exception("bank_pack_selected error")
        await callback.answer("Ошибка. Попробуйте позже.", show_alert=True)


@router.callback_query(F.data == "bank_transfer:cancel")
async def bank_transfer_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена оплаты переводом."""
    await state.clear()
    await callback.message.answer(
        "Оплата отменена. Вы можете купить генерации за Stars в магазине.",
        reply_markup=main_menu_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "bank_transfer:retry")
async def bank_transfer_retry(callback: CallbackQuery, state: FSMContext):
    """Сброс счётчика попыток после 3 неудач — можно отправить чек снова."""
    await state.update_data(bank_receipt_attempts=0)
    try:
        await callback.message.edit_text(
            "🔄 Отправьте скриншот чека ещё раз. Счётчик попыток сброшен.",
            reply_markup=None,
        )
    except Exception:
        await callback.message.answer(
            "🔄 Отправьте скриншот чека ещё раз. Счётчик попыток сброшен."
        )
    await callback.answer()


def _receipt_log_rel_path(file_path: str) -> str:
    """Путь к файлу чека относительно storage_base_path для хранения в логе."""
    base = getattr(settings, "storage_base_path", "")
    if base and file_path.startswith(base):
        return os.path.relpath(file_path, base)
    return os.path.basename(file_path) or file_path


def _create_receipt_log(
    db: Session,
    telegram_user_id: str,
    file_path: str,
    raw_vision_response: str,
    regex_pattern: str,
    extracted_amount_rub: float | None,
    expected_rub: float,
    match_success: bool,
    pack_id: str,
    payment_id: str | None = None,
    error_message: str | None = None,
    vision_model: str | None = None,
    card_match_success: bool | None = None,
    extracted_card_first4: str | None = None,
    extracted_card_last4: str | None = None,
    receipt_fingerprint: str | None = None,
    extracted_receipt_dt: datetime | None = None,
    extracted_comment: str | None = None,
    comment_match_success: bool | None = None,
    rejection_reason: str | None = None,
) -> None:
    """Записать одну попытку распознавания чека в bank_transfer_receipt_log."""
    user = db.query(User).filter(User.telegram_id == telegram_user_id).one_or_none()
    user_id = user.id if user else None
    rel_path = _receipt_log_rel_path(file_path)
    log = BankTransferReceiptLog(
        telegram_user_id=telegram_user_id,
        user_id=user_id,
        file_path=rel_path,
        raw_vision_response=raw_vision_response or "",
        regex_pattern=regex_pattern or "",
        extracted_amount_rub=extracted_amount_rub,
        expected_rub=expected_rub,
        match_success=match_success,
        pack_id=pack_id,
        payment_id=payment_id,
        error_message=error_message,
        vision_model=vision_model,
        card_match_success=card_match_success,
        extracted_card_first4=extracted_card_first4,
        extracted_card_last4=extracted_card_last4,
        receipt_fingerprint=receipt_fingerprint,
        extracted_receipt_dt=extracted_receipt_dt,
        extracted_comment=extracted_comment,
        comment_match_success=comment_match_success,
        rejection_reason=rejection_reason,
    )
    db.add(log)
    db.flush()


BANK_RECEIPT_RATE_LIMIT = 10         # максимум попыток в час
BANK_RECEIPT_RATE_WINDOW = 3600      # TTL ключа, сек
BANK_RECEIPT_MAX_AGE_HOURS = 48      # чек не старше N часов (0 = не проверять)
# Проверка и показ комментария к переводу отключены: не все банки позволяют указать комментарий в переводе
BANK_RECEIPT_COMMENT_DISABLED = True
BANK_RECEIPT_MAX_ATTEMPTS = 3        # после N неудачных попыток показать контакты поддержки
BANK_RECEIPT_DUPLICATE_TTL = 72 * 3600  # 72 ч в Redis для отпечатка


def _check_receipt_rate_limit(telegram_id: str) -> bool:
    """True если лимит НЕ превышен. False если слишком много попыток."""
    key = f"bank_receipt_attempts:{telegram_id}"
    try:
        current = redis_client.incr(key)
        if current == 1:
            redis_client.expire(key, BANK_RECEIPT_RATE_WINDOW)
        return current <= BANK_RECEIPT_RATE_LIMIT
    except Exception:
        return True  # fail open


def _normalize_comment(text: str | None) -> str:
    """Нормализовать комментарий для сравнения: нижний регистр, без лишних пробелов и символов."""
    if not text:
        return ""
    import re as _re
    return _re.sub(r"\s+", " ", text.strip().lower())


def _check_duplicate_fingerprint(fingerprint: str | None, telegram_id: str) -> str | None:
    """Проверить дубликат по отпечатку чека. Возвращает rejection_reason или None."""
    if not fingerprint:
        return None
    key = f"receipt_fingerprint:{fingerprint}"
    try:
        existing = redis_client.get(key)
        if existing:
            existing_str = existing if isinstance(existing, str) else existing.decode()
            if existing_str == telegram_id:
                return "duplicate_receipt"
            else:
                return "duplicate_cross_user"
        return None
    except Exception:
        return None


def _mark_fingerprint_used(fingerprint: str | None, telegram_id: str) -> None:
    """Записать в Redis использованный отпечаток чека."""
    if not fingerprint:
        return
    key = f"receipt_fingerprint:{fingerprint}"
    try:
        redis_client.set(key, telegram_id, ex=BANK_RECEIPT_DUPLICATE_TTL)
    except Exception:
        pass


async def _process_bank_receipt(message: Message, state: FSMContext, file_path: str):
    """Общая логика: распознать чек → проверить сумму, карту, комментарий (если не отключён), свежесть, дубликат → зачислить → записать лог."""
    from app.services.llm.receipt_parser import AMOUNT_REGEX_PATTERN, analyze_receipt, amounts_match

    data = await state.get_data()
    expected_rub = data.get("bank_expected_rub")
    pack_id = data.get("bank_pack_id")
    pack_name = data.get("bank_pack_name", pack_id)
    tokens = data.get("bank_tokens")
    stars = data.get("bank_stars")
    expected_receipt_code = data.get("bank_receipt_code", "")
    telegram_id = str(message.from_user.id)

    if not expected_rub or not pack_id or not tokens:
        await state.clear()
        await message.answer("Сессия истекла. Начните оплату заново в магазине.", reply_markup=main_menu_keyboard())
        return

    # --- Rate limit (6.4) ---
    if not _check_receipt_rate_limit(telegram_id):
        await message.answer(
            "⚠️ Слишком много попыток. Пожалуйста, подождите час и попробуйте снова."
        )
        logger.warning("bank_receipt_rate_limited", extra={"user_id": telegram_id})
        return

    wait_msg = await message.answer("⏳ Проверяем чек...")

    try:
        with get_db_session() as db:
            bank_svc = BankTransferSettingsService(db)
            receipt_config = bank_svc.get_receipt_config()
            effective = bank_svc.get_effective()

        result = analyze_receipt(file_path, config=receipt_config)
        amount = result.get("amount_rub")
        raw_response = result.get("raw_response", "")
        regex_pattern = result.get("regex_pattern", AMOUNT_REGEX_PATTERN)
        vision_model = result.get("vision_model")
        card_first4 = result.get("card_first4")
        card_last4 = result.get("card_last4")
        receipt_dt = result.get("receipt_dt")       # datetime | None
        extracted_comment = result.get("comment")   # str | None
        fingerprint = result.get("receipt_fingerprint")

        tol_abs = receipt_config["amount_tolerance_abs"]
        tol_pct = receipt_config["amount_tolerance_pct"]
        amount_ok = amounts_match(amount, expected_rub, tolerance_abs=tol_abs, tolerance_pct=tol_pct)

        # --- Проверка карты (п.2) ---
        card_number = effective.get("card_number", "")
        card_digits = "".join(c for c in card_number if c.isdigit())
        if len(card_digits) < 8:
            card_match = True
        elif card_first4 and card_last4:
            expected_first4 = card_digits[:4]
            expected_last4 = card_digits[-4:]
            card_match = (card_first4 == expected_first4 and card_last4 == expected_last4)
        elif card_last4:
            expected_last4 = card_digits[-4:]
            card_match = (card_last4 == expected_last4)
        else:
            card_match = False

        # --- Проверка комментария (6.3) ---
        comment_match: bool | None = None
        if expected_receipt_code:
            norm_expected = _normalize_comment(expected_receipt_code)
            norm_actual = _normalize_comment(extracted_comment)
            comment_match = norm_expected in norm_actual if norm_actual else False

        # --- Свежесть чека (6.2 + п.12) ---
        receipt_fresh = True
        receipt_age_reason: str | None = None
        if BANK_RECEIPT_MAX_AGE_HOURS > 0:
            if receipt_dt is None:
                receipt_fresh = False
                receipt_age_reason = "receipt_date_not_found"
            else:
                from datetime import timedelta
                age = datetime.now(timezone.utc) - receipt_dt.astimezone(timezone.utc)
                if age > timedelta(hours=BANK_RECEIPT_MAX_AGE_HOURS):
                    receipt_fresh = False
                    receipt_age_reason = "receipt_too_old"

        # --- Дубликат (6.1, 6.5) ---
        dup_reason = _check_duplicate_fingerprint(fingerprint, telegram_id)

        # --- Итоговое решение ---
        rejection_reason: str | None = None
        if not amount_ok:
            rejection_reason = "amount_mismatch"
        elif not card_match:
            rejection_reason = "card_mismatch"
        elif not BANK_RECEIPT_COMMENT_DISABLED and comment_match is False:
            rejection_reason = "comment_mismatch"
        elif not receipt_fresh:
            rejection_reason = receipt_age_reason
        elif dup_reason:
            rejection_reason = dup_reason

        overall_success = rejection_reason is None

        # Общие kwargs для логирования
        log_kwargs = dict(
            raw_vision_response=raw_response,
            regex_pattern=regex_pattern,
            extracted_amount_rub=amount,
            expected_rub=expected_rub,
            pack_id=pack_id,
            vision_model=vision_model,
            card_match_success=card_match,
            extracted_card_first4=card_first4,
            extracted_card_last4=card_last4,
            receipt_fingerprint=fingerprint,
            extracted_receipt_dt=receipt_dt,
            extracted_comment=extracted_comment,
            comment_match_success=comment_match,
            rejection_reason=rejection_reason,
        )

        if overall_success:
            reference = str(uuid4())
            payment_id_created = None
            with get_db_session() as db:
                payment_service = PaymentService(db)
                payment = payment_service.credit_tokens_manual(
                    telegram_user_id=telegram_id,
                    pack_id=pack_id,
                    stars_amount=stars,
                    tokens_granted=tokens,
                    reference=reference,
                )
                if payment:
                    payment_id_created = payment.id
                    user = db.query(User).filter(User.telegram_id == telegram_id).one_or_none()
                    balance = user.token_balance if user else tokens
                else:
                    balance = tokens
                _create_receipt_log(
                    db,
                    telegram_user_id=telegram_id,
                    file_path=file_path,
                    match_success=True,
                    payment_id=payment_id_created,
                    **log_kwargs,
                )
                db.commit()

            # Отметить отпечаток как использованный
            _mark_fingerprint_used(fingerprint, telegram_id)

            await state.clear()
            success_text = effective["success_message"].format(
                pack_name=pack_name, tokens=tokens, balance=balance
            )
            await wait_msg.edit_text(success_text, parse_mode="Markdown")
            logger.info(
                "bank_transfer_success",
                extra={"user_id": telegram_id, "pack_id": pack_id, "amount_rub": amount, "expected_rub": expected_rub},
            )
        else:
            attempts = (data.get("bank_receipt_attempts") or 0) + 1
            await state.update_data(bank_receipt_attempts=attempts)
            with get_db_session() as db:
                _create_receipt_log(
                    db,
                    telegram_user_id=telegram_id,
                    file_path=file_path,
                    match_success=False,
                    **log_kwargs,
                )
                db.commit()
            if attempts >= BANK_RECEIPT_MAX_ATTEMPTS:
                support_text = (
                    f"❌ *Не удалось подтвердить оплату* (попытка {attempts}).\n\n"
                    "Обратитесь в поддержку: /paysupport — укажите время перевода и приложите чек, мы проверим вручную.\n\n"
                    "Или попробуйте отправить чек ещё раз."
                )
                retry_kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="bank_transfer:retry")],
                    [InlineKeyboardButton(text="📋 В меню", callback_data="bank_transfer:cancel")],
                ])
                await wait_msg.edit_text(support_text, parse_mode="Markdown", reply_markup=retry_kb)
            else:
                fail_text = effective["amount_mismatch_message"]
                if BANK_RECEIPT_COMMENT_DISABLED:
                    fail_text = fail_text.replace(
                        "Убедитесь, что на скриншоте видны: сумма перевода, номер карты получателя, комментарий к переводу и дата.",
                        "Убедитесь, что на скриншоте видны: сумма перевода, номер карты получателя и дата.",
                    ).replace("комментарий к переводу и ", "").replace("комментарий к переводу, и ", "и ")
                await wait_msg.edit_text(
                    f"{fail_text}\n\n_Попытка {attempts} из {BANK_RECEIPT_MAX_ATTEMPTS}. Можно отправить другой скриншот._",
                    parse_mode="Markdown",
                )
            logger.warning(
                "bank_transfer_mismatch",
                extra={
                    "user_id": telegram_id,
                    "amount": amount,
                    "expected": expected_rub,
                    "rejection_reason": rejection_reason,
                    "attempt": attempts,
                },
            )
    except Exception as e:
        logger.exception("bank_receipt_processing_error")
        with get_db_session() as db:
            _create_receipt_log(
                db,
                telegram_user_id=telegram_id,
                file_path=file_path,
                raw_vision_response="",
                regex_pattern=AMOUNT_REGEX_PATTERN,
                extracted_amount_rub=None,
                expected_rub=expected_rub,
                match_success=False,
                pack_id=pack_id,
                error_message=str(e),
            )
            db.commit()
        await wait_msg.edit_text(
            "⚠️ Ошибка при проверке чека. Попробуйте отправить ещё раз."
        )


@router.message(BotStates.bank_transfer_waiting_receipt, F.photo)
async def bank_receipt_photo(message: Message, state: FSMContext, bot: Bot):
    """Приём чека как фото."""
    try:
        photo = message.photo[-1]  # наибольшее разрешение
        file = await bot.get_file(photo.file_id)

        # Сохраняем во временную директорию
        receipt_dir = os.path.join(settings.storage_base_path, "receipts")
        os.makedirs(receipt_dir, exist_ok=True)
        ext = "jpg"
        local_path = os.path.join(receipt_dir, f"receipt_{uuid4()}.{ext}")
        await bot.download_file(file.file_path, local_path)

        await _process_bank_receipt(message, state, local_path)
    except Exception:
        logger.exception("bank_receipt_photo error")
        await message.answer("⚠️ Ошибка при загрузке фото. Попробуйте ещё раз.")


@router.message(BotStates.bank_transfer_waiting_receipt, F.document)
async def bank_receipt_document(message: Message, state: FSMContext, bot: Bot):
    """Приём чека как документа (изображение)."""
    doc = message.document
    mime = (doc.mime_type or "").lower()
    fname = (doc.file_name or "").lower()

    allowed_mimes = {"image/jpeg", "image/png", "image/webp", "image/jpg"}
    allowed_exts = {".jpg", ".jpeg", ".png", ".webp"}
    ext = os.path.splitext(fname)[1] if fname else ""

    if mime not in allowed_mimes and ext not in allowed_exts:
        if "pdf" in mime or fname.endswith(".pdf"):
            await message.answer(
                "📄 PDF пока не поддерживается. Пожалуйста, сделайте скриншот чека и отправьте как фото."
            )
        else:
            await message.answer(
                "Поддерживаются только изображения: JPG, PNG, WEBP.\n"
                "Отправьте скриншот чека как фото или файл изображения."
            )
        return

    try:
        file = await bot.get_file(doc.file_id)
        receipt_dir = os.path.join(settings.storage_base_path, "receipts")
        os.makedirs(receipt_dir, exist_ok=True)
        if ext in allowed_exts:
            save_ext = ext.lstrip(".")
        else:
            save_ext = "jpg"
        local_path = os.path.join(receipt_dir, f"receipt_{uuid4()}.{save_ext}")
        await bot.download_file(file.file_path, local_path)

        await _process_bank_receipt(message, state, local_path)
    except Exception:
        logger.exception("bank_receipt_document error")
        await message.answer("⚠️ Ошибка при загрузке файла. Попробуйте ещё раз.")


@router.message(BotStates.bank_transfer_waiting_receipt)
async def bank_receipt_wrong_input(message: Message):
    """Неверный ввод в состоянии ожидания чека."""
    await message.answer(
        "📸 Отправьте скриншот или фото чека перевода.\n"
        "Поддерживаются: фото, JPG, PNG, WEBP."
    )


@router.message(BotStates.waiting_for_prompt)
async def waiting_prompt_wrong_input(message: Message):
    """User sent non-text in waiting_for_prompt."""
    await message.answer(t("flow.prompt_placeholder", "Опишите свою идею текстом. Например: «Сделай в стиле аниме»"))


# ===========================================
# Session-based flow: Take A/B/C, Favorites, HD
# ===========================================

@router.callback_query(F.data.startswith("choose:"))
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
                await callback.answer("❌ Снимок не найден", show_alert=True)
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
            session_id = take.session_id
            user_is_moderator = getattr(user, "is_moderator", False)
            fav_id = str(fav.id) if fav else None
            hd_svc = HDBalanceService(db)
            balance = hd_svc.get_balance(user)

            trend_label = "Снимок"
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

        if (is_free or not session_id) and not user_is_moderator:
            await _show_paywall_after_free_take(callback.message, telegram_id, take_id, variant)
        else:
            is_collection = False
            collection_info = ""
            if session_id:
                with get_db_session() as db:
                    session_svc = SessionService(db)
                    session = session_svc.get_session(session_id)
                    if session and session_svc.is_collection(session):
                        is_collection = True
                        fav_svc_c = FavoriteService(db)
                        fav_count_c = fav_svc_c.count_favorites(session.id)
                        selected_c = fav_svc_c.count_selected_for_hd(session.id)
                        hd_rem_c = session_svc.hd_remaining(session)
                        collection_info = (
                            f"\n\nВсего превью: {session.takes_used * 3}/{session.takes_limit * 3}\n"
                            f"4K осталось: {hd_rem_c} | В избранном: {fav_count_c} (для 4K: {selected_c})"
                        )

            await state.set_state(BotStates.viewing_take_result)
            await state.update_data(current_take_id=take_id)
            short_menu_buttons = []
            if fav_id and balance.get("total", 0) > 0 and not is_collection:
                short_menu_buttons.append([
                    InlineKeyboardButton(text="🖼 Забрать 4K для этого", callback_data=f"deliver_hd_one:{fav_id}"),
                ])
            if is_collection:
                short_menu_buttons.append([
                    InlineKeyboardButton(text="📸 Следующий образ", callback_data="take_more"),
                    InlineKeyboardButton(text="📋 Избранное", callback_data="open_favorites"),
                ])
            else:
                short_menu_buttons.append([
                    InlineKeyboardButton(text="📸 Ещё снимок", callback_data="take_more"),
                    InlineKeyboardButton(text="📋 В избранное", callback_data="open_favorites"),
                ])
            await callback.message.answer(
                f"{trend_label} · Вариант {variant} в избранном.{collection_info}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=short_menu_buttons),
            )

    except Exception:
        logger.exception("choose_variant error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка. Попробуйте снова.", show_alert=True)


async def _show_paywall_after_free_take(message: Message, telegram_id: str, take_id: str, variant: str):
    """Show contextual paywall after free take — all ladder packs."""
    try:
        with get_db_session() as db:
            audit = AuditService(db)
            user_svc = UserService(db)
            user = user_svc.get_by_telegram_id(telegram_id)
            is_trial_eligible = user and not getattr(user, "trial_purchased", True)

            payment_service = PaymentService(db)
            all_packs = payment_service.list_product_ladder_packs()

            buttons_data = []
            position = 1
            for p in all_packs:
                if getattr(p, "pack_subtype", "standalone") == "collection" and not getattr(p, "playlist", None):
                    continue
                if p.is_trial and not is_trial_eligible:
                    continue
                buttons_data.append({
                    "id": p.id, "emoji": p.emoji,
                    "name": p.name, "stars_price": p.stars_price,
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

        rate = getattr(settings, "star_to_rub", 1.3)
        buttons = []
        for bd in buttons_data:
            outcome = bd.get("outcome", "")
            label = f"{bd['emoji']} {bd['name']}: {outcome} — {format_stars_rub(bd['stars_price'], rate)}" if outcome else f"{bd['emoji']} {bd['name']} — {format_stars_rub(bd['stars_price'], rate)}"
            buttons.append([InlineKeyboardButton(text=label, callback_data=f"paywall:{bd['id']}")])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer(
            "👀 Смотри бесплатно, плати только если нравится!\n\n"
            "🎬 Получи 4K версию без watermark:",
            reply_markup=keyboard,
        )
    except Exception:
        logger.exception("_show_paywall_after_free_take error")
        try:
            await message.answer(
                "Не удалось загрузить тарифы. Выберите фотосессию в меню (🛒 Купить тариф)."
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("add_var:"))
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
                await callback.answer("❌ Снимок не найден", show_alert=True)
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

            trend_label = "Снимок"
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

        await callback.answer(f"⭐ Добавлено: {trend_label}, вариант {variant}")
    except Exception:
        logger.exception("add_variant_to_favorites error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data == "take_more")
async def take_more(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Start another Take within the session. Collection mode: auto-advance with same photo."""
    telegram_id = str(callback.from_user.id)
    try:
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
                else:
                    telegram_id = str(callback.from_user.id)
                    text, kb_dict = build_balance_tariffs_message(db, telegram_id)
                    if kb_dict is None:
                        await callback.message.answer("Тарифы временно недоступны.", reply_markup=main_menu_keyboard())
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


def _build_favorites_message(db, user) -> tuple[str | None, list[list[dict]], int]:
    """Собрать текст и кнопки списка избранного. Возвращает (text, rows, favorites_count) или (None, [], 0) если пусто."""
    fav_svc = FavoriteService(db)
    hd_svc = HDBalanceService(db)
    session_svc = SessionService(db)

    all_favorites = fav_svc.list_favorites_for_user(user.id)
    # Показываем только актуальные: уже выданные в 4K не показываем в списке
    favorites = [f for f in all_favorites if f.hd_status != "delivered"]
    if not favorites:
        return (None, [], 0)

    balance = hd_svc.get_balance(user)
    session = session_svc.get_active_session(user.id)
    is_collection = session and session_svc.is_collection(session)
    hd_rem = session_svc.hd_remaining(session) if session else 0
    selected_count = fav_svc.count_selected_for_hd(session.id) if session else 0
    has_session = session is not None

    take_ids = list({f.take_id for f in favorites if f.take_id})
    takes = db.query(TakeModel).filter(TakeModel.id.in_(take_ids)).all() if take_ids else []
    take_by_id = {t.id: t for t in takes}
    trend_ids = list({t.trend_id for t in takes if getattr(t, "trend_id", None)})
    trends = db.query(TrendModel).filter(TrendModel.id.in_(trend_ids)).all() if trend_ids else []
    trend_by_id = {tr.id: tr for tr in trends}

    now = datetime.now(timezone.utc)
    favorites_data = []
    for f in favorites:
        rendering_too_long = False
        if f.hd_status == "rendering" and f.updated_at:
            elapsed_min = (now - f.updated_at).total_seconds() / 60.0
            if elapsed_min > 5:
                rendering_too_long = True
        trend_label = "Снимок"
        take = take_by_id.get(f.take_id) if f.take_id else None
        if take and getattr(take, "trend_id", None):
            trend = trend_by_id.get(take.trend_id)
            if trend:
                trend_label = f"{trend.emoji} {trend.name}"
        favorites_data.append({
            "id": f.id,
            "variant": f.variant,
            "hd_status": f.hd_status,
            "selected_for_hd": getattr(f, "selected_for_hd", False),
            "rendering_too_long": rendering_too_long,
            "trend_label": trend_label,
        })

    lines = [f"⭐ Избранное ({len(favorites_data)})\n"]
    button_rows = []
    for i, fav in enumerate(favorites_data, 1):
        if fav["hd_status"] == "rendering":
            status_icon = "⏳"
        elif fav["selected_for_hd"]:
            status_icon = "🟢 4K"
        else:
            status_icon = ""
        trend_label = fav.get("trend_label") or "Снимок"
        lines.append(f"{i}. {trend_label} · Вариант {fav['variant']} {status_icon}")

        row = []
        if fav["hd_status"] == "none":
            if fav["selected_for_hd"]:
                row.append({"text": f"↩️ Убрать 4K #{i}", "callback_data": f"deselect_hd:{fav['id']}"})
            else:
                row.append({"text": f"🟢 Выбрать 4K #{i}", "callback_data": f"select_hd:{fav['id']}"})
            row.append({"text": f"❌ #{i}", "callback_data": f"remove_fav:{fav['id']}"})
        if fav["rendering_too_long"]:
            row.append({"text": f"⚠️ Проблема #{i}", "callback_data": f"hd_problem:{fav['id']}"})
        if row:
            button_rows.append(row)

    if is_collection and session:
        lines.append(f"\n4K осталось: {hd_rem} | Отмечено для 4K: {selected_count}")
    else:
        lines.append(f"\n4K баланс: {balance['total']}")

    action_buttons = []
    removable_count = sum(1 for f in favorites_data if f["hd_status"] != "delivered")
    pending_count = sum(1 for f in favorites_data if f["hd_status"] == "none")
    if is_collection and selected_count > 0:
        action_buttons.append({"text": f"🖼 Забрать 4K альбомом ({selected_count})", "callback_data": "deliver_hd_album"})
    elif pending_count > 0 and balance["total"] > 0:
        action_buttons.append({"text": "🖼 Забрать 4K", "callback_data": "deliver_hd"})
    if removable_count > 0:
        action_buttons.append({"text": "🗑 Очистить все", "callback_data": "favorites_clear_all"})
    if has_session:
        action_buttons.append({"text": "📸 Назад к сессии", "callback_data": "session_status"})
    if action_buttons:
        button_rows.append(action_buttons)

    return ("\n".join(lines), button_rows, len(favorites_data))


def _favorites_rows_to_keyboard(rows: list[list[dict]]) -> InlineKeyboardMarkup | None:
    """Преобразовать rows из _build_favorites_message в InlineKeyboardMarkup."""
    if not rows:
        return None
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=b["text"], callback_data=b["callback_data"]) for b in row] for row in rows]
    )
    return keyboard


@router.callback_query(F.data == "open_favorites")
async def open_favorites(callback: CallbackQuery, state: FSMContext):
    """Show favorites list with HD selection controls."""
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
            text, rows, favorites_count = _build_favorites_message(db, user)

            audit = AuditService(db)
            audit.log(
                actor_type="user",
                actor_id=telegram_id,
                action="favorites_opened",
                entity_type="user",
                entity_id=user.id,
                payload={"count": favorites_count},
            )

        if text is None:
            await callback.answer("Избранное пусто", show_alert=True)
            return

        keyboard = _favorites_rows_to_keyboard(rows)
        await callback.message.answer(text, reply_markup=keyboard)
        await state.set_state(BotStates.viewing_favorites)
        await callback.answer()
    except Exception:
        logger.exception("open_favorites error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data == "favorites_clear_all")
async def clear_all_favorites(callback: CallbackQuery, state: FSMContext):
    """Удалить все избранное (кроме уже выданных 4K)."""
    telegram_id = str(callback.from_user.id)
    try:
        with get_db_session() as db:
            user_svc = UserService(db)
            user = user_svc.get_or_create_user(
                telegram_id,
                telegram_username=callback.from_user.username,
                telegram_first_name=callback.from_user.first_name,
                telegram_last_name=callback.from_user.last_name,
            )
            fav_svc = FavoriteService(db)
            deleted = fav_svc.clear_all_for_user(user.id)
        if deleted > 0:
            await callback.answer(f"🗑 Удалено из избранного: {deleted}")
            try:
                with get_db_session() as db:
                    user_svc = UserService(db)
                    user = user_svc.get_by_telegram_id(telegram_id)
                    if user:
                        text, rows, _ = _build_favorites_message(db, user)
                        if text:
                            kb = _favorites_rows_to_keyboard(rows)
                            await callback.message.edit_text(text, reply_markup=kb)
                        else:
                            await callback.message.edit_text("⭐ Избранное\n\nСписок пуст.", reply_markup=None)
            except Exception as e:
                logger.debug("favorites_clear_all refresh list failed", extra={"error": str(e)})
        else:
            await callback.answer("Нечего удалять (или всё уже 4K)", show_alert=True)
    except Exception:
        logger.exception("clear_all_favorites error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("remove_fav:"))
async def remove_favorite(callback: CallbackQuery, state: FSMContext):
    """Remove a favorite."""
    telegram_id = str(callback.from_user.id)
    fav_id = callback.data.split(":", 1)[1]
    try:
        with get_db_session() as db:
            fav_svc = FavoriteService(db)
            removed = fav_svc.remove_favorite(fav_id)
        if removed:
            await callback.answer("Удалено из избранного")
            try:
                with get_db_session() as db:
                    user_svc = UserService(db)
                    user = user_svc.get_by_telegram_id(telegram_id)
                    if user:
                        text, rows, _ = _build_favorites_message(db, user)
                        if text:
                            kb = _favorites_rows_to_keyboard(rows)
                            await callback.message.edit_text(text, reply_markup=kb)
                        else:
                            await callback.message.edit_text("⭐ Избранное\n\nСписок пуст.", reply_markup=None)
            except Exception as e:
                logger.debug("remove_fav refresh list failed", extra={"error": str(e)})
        else:
            await callback.answer("Не удалось удалить (возможно, уже 4K)")
    except Exception:
        logger.exception("remove_favorite error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("select_hd:"))
async def select_hd_callback(callback: CallbackQuery, state: FSMContext):
    """Mark favorite as selected for HD delivery."""
    telegram_id = str(callback.from_user.id)
    fav_id = callback.data.split(":", 1)[1]
    try:
        with get_db_session() as db:
            user_svc = UserService(db)
            user = user_svc.get_or_create_user(
                telegram_id,
                telegram_username=callback.from_user.username,
                telegram_first_name=callback.from_user.first_name,
                telegram_last_name=callback.from_user.last_name,
            )
            fav_svc = FavoriteService(db)
            session_svc = SessionService(db)
            fav = fav_svc.get_favorite(fav_id)
            if not fav or str(fav.user_id) != str(user.id):
                await callback.answer("❌ Не найдено", show_alert=True)
                return
            session_id = fav.session_id
            if not session_id:
                await callback.answer("❌ Нет сессии", show_alert=True)
                return
            ok = fav_svc.select_for_hd(fav_id, session_id)
        if ok:
            await callback.answer("🟢 Отмечено для 4K")
            try:
                with get_db_session() as db:
                    user_svc = UserService(db)
                    user = user_svc.get_by_telegram_id(telegram_id)
                    if user:
                        text, rows, _ = _build_favorites_message(db, user)
                        if text:
                            kb = _favorites_rows_to_keyboard(rows)
                            await callback.message.edit_text(text, reply_markup=kb)
            except Exception as e:
                logger.debug("select_hd refresh list failed", extra={"error": str(e)})
        else:
            await callback.answer("❌ Лимит 4K достигнут", show_alert=True)
    except Exception:
        logger.exception("select_hd error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("deselect_hd:"))
async def deselect_hd_callback(callback: CallbackQuery, state: FSMContext):
    """Unmark favorite from 4K selection."""
    telegram_id = str(callback.from_user.id)
    fav_id = callback.data.split(":", 1)[1]
    try:
        with get_db_session() as db:
            user_svc = UserService(db)
            user = user_svc.get_or_create_user(
                telegram_id,
                telegram_username=callback.from_user.username,
                telegram_first_name=callback.from_user.first_name,
                telegram_last_name=callback.from_user.last_name,
            )
            fav_svc = FavoriteService(db)
            fav = fav_svc.get_favorite(fav_id)
            if not fav or str(fav.user_id) != str(user.id):
                await callback.answer("❌ Не найдено", show_alert=True)
                return
            fav_svc.deselect_for_hd(fav_id)
        await callback.answer("↩️ 4K отменено")
        try:
            with get_db_session() as db:
                user_svc = UserService(db)
                user = user_svc.get_by_telegram_id(telegram_id)
                if user:
                    text, rows, _ = _build_favorites_message(db, user)
                    if text:
                        kb = _favorites_rows_to_keyboard(rows)
                        await callback.message.edit_text(text, reply_markup=kb)
        except Exception as e:
            logger.debug("deselect_hd refresh list failed", extra={"error": str(e)})
    except Exception:
        logger.exception("deselect_hd error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("hd_problem:"))
async def hd_problem_callback(callback: CallbackQuery, state: FSMContext):
    """Report a problem with 4K rendering."""
    telegram_id = str(callback.from_user.id)
    fav_id = callback.data.split(":", 1)[1]
    try:
        with get_db_session() as db:
            user_svc = UserService(db)
            user = user_svc.get_or_create_user(
                telegram_id,
                telegram_username=callback.from_user.username,
                telegram_first_name=callback.from_user.first_name,
                telegram_last_name=callback.from_user.last_name,
            )
            fav_svc = FavoriteService(db)
            fav = fav_svc.get_favorite(fav_id)
            if not fav:
                await callback.answer("❌ Не найдено", show_alert=True)
                return
            session = db.query(SessionModel).filter(SessionModel.id == fav.session_id).one_or_none() if fav.session_id else None
            correlation_id = session.collection_run_id if session else None

            comp_svc = CompensationService(db)
            comp_svc.report_hd_problem(user.id, fav_id, correlation_id)

        await callback.answer("📩 Проблема зафиксирована. Мы разберёмся.", show_alert=True)
    except Exception:
        logger.exception("hd_problem error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data == "deliver_hd_album")
async def deliver_hd_album_callback(callback: CallbackQuery, state: FSMContext):
    """Deliver 4K for all favorites marked as selected_for_hd."""
    telegram_id = str(callback.from_user.id)
    try:
        with get_db_session() as db:
            user_svc = UserService(db)
            user = user_svc.get_or_create_user(
                telegram_id,
                telegram_username=callback.from_user.username,
                telegram_first_name=callback.from_user.first_name,
                telegram_last_name=callback.from_user.last_name,
            )
            fav_svc = FavoriteService(db)
            session_svc = SessionService(db)
            session = session_svc.get_active_session(user.id)
            if not session:
                sessions = (
                    db.query(SessionModel)
                    .filter(SessionModel.user_id == user.id)
                    .order_by(SessionModel.created_at.desc())
                    .first()
                )
                session = sessions

            if not session:
                await callback.answer("❌ Нет сессии", show_alert=True)
                return

            selected = fav_svc.list_selected_for_hd(session.id)
            if not selected:
                await callback.answer("❌ Не выбрано ни одного 4K", show_alert=True)
                return

            hd_svc = HDBalanceService(db)
            balance = hd_svc.get_balance(user)
            can_deliver = min(len(selected), balance["total"])
            if can_deliver == 0:
                await callback.answer("❌ Недостаточно 4K на балансе", show_alert=True)
                return

            selected_ids = [f.id for f in selected[:can_deliver]]

        await callback.message.answer(
            f"🖼 Запущена 4K выдача для {len(selected_ids)} избранных.\n"
            f"Ожидайте файлы в чате..."
        )

        from app.core.celery_app import celery_app as _celery
        chat_id = str(callback.message.chat.id)
        for fav_id in selected_ids:
            _celery.send_task(
                "app.workers.tasks.deliver_hd.deliver_hd",
                args=[fav_id],
                kwargs={"status_chat_id": chat_id},
            )
        await callback.answer(f"🖼 Запущено {len(selected_ids)} 4K")
    except Exception:
        logger.exception("deliver_hd_album error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("deliver_hd_one:"))
async def deliver_hd_one_callback(callback: CallbackQuery, state: FSMContext):
    """Deliver 4K for one favorite (short path after choosing variant)."""
    telegram_id = str(callback.from_user.id)
    parts = callback.data.split(":", 1)
    if len(parts) != 2:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    fav_id = parts[1]
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
                await callback.answer("❌ Избранное не найдено", show_alert=True)
                return
            if fav.hd_status != "none":
                await callback.answer("4K уже выдан или в обработке", show_alert=True)
                return
            balance = hd_svc.get_balance(user)
            if balance.get("total", 0) < 1:
                await callback.answer("❌ Недостаточно 4K на балансе", show_alert=True)
                return

        from app.core.celery_app import celery_app as _celery

        chat_id = str(callback.message.chat.id)
        _celery.send_task(
            "app.workers.tasks.deliver_hd.deliver_hd",
            args=[fav_id],
            kwargs={"status_chat_id": chat_id},
        )
        await callback.answer("🖼 Запущена выдача 4K")
        await callback.message.answer("⏳ Ожидайте файл в чате.")
    except Exception:
        logger.exception("deliver_hd_one_callback error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data == "deliver_hd")
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
            can_deliver = min(len(pending), balance["total"])

            if can_deliver == 0:
                await callback.answer("❌ Недостаточно 4K на балансе", show_alert=True)
                return

            pending_ids = [f.id for f in pending[:can_deliver]]

        from app.core.celery_app import celery_app as _celery

        chat_id = str(callback.message.chat.id)
        launched = 0
        for fav_id in pending_ids:
            _celery.send_task(
                "app.workers.tasks.deliver_hd.deliver_hd",
                args=[fav_id],
                kwargs={"status_chat_id": chat_id},
            )
            launched += 1

        await callback.answer(f"🖼 Запущена 4K выдача ({launched} шт.)")
        await callback.message.answer(f"⏳ 4K выдача запущена для {launched} избранных. Ожидайте файлы...")
    except Exception:
        logger.exception("deliver_hd_callback error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data == "session_status")
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
            session_svc = SessionService(db)
            hd_svc = HDBalanceService(db)
            fav_svc = FavoriteService(db)

            session = session_svc.get_active_session(user.id)
            balance = hd_svc.get_balance(user)

            if not session:
                await callback.message.answer(
                    "📸 Нет активной фотосессии.\n"
                    "Купите пакет, чтобы начать!",
                    reply_markup=main_menu_keyboard(),
                )
                await callback.answer()
                return

            fav_count = fav_svc.count_favorites(session.id)
            remaining = session.takes_limit - session.takes_used
            is_collection = session_svc.is_collection(session)
            hd_rem = session_svc.hd_remaining(session)
            selected_count = fav_svc.count_selected_for_hd(session.id)
            pack_id = session.pack_id
            takes_used = session.takes_used
            takes_limit = session.takes_limit
            hd_limit = session.hd_limit

        buttons = []
        if remaining > 0:
            buttons.append([InlineKeyboardButton(text="📸 Сделать снимок", callback_data="take_more")])
        buttons.append([InlineKeyboardButton(text="⭐ Открыть избранное", callback_data="open_favorites")])

        if is_collection and selected_count > 0:
            buttons.append([InlineKeyboardButton(
                text=f"🖼 Забрать 4K альбомом ({selected_count})",
                callback_data="deliver_hd_album",
            )])
        elif fav_count > 0 and balance["total"] > 0:
            buttons.append([InlineKeyboardButton(text="🖼 Забрать 4K", callback_data="deliver_hd")])

        if pack_id == "trial":
            buttons.append([InlineKeyboardButton(text="⬆️ Neo Start — доплата 54⭐", callback_data="upgrade:neo_start")])
            buttons.append([InlineKeyboardButton(text="⬆️ Neo Pro — доплата 439⭐", callback_data="upgrade:neo_pro")])

        if is_collection:
            status_text = (
                f"📸 Ваша коллекция\n\n"
                f"Всего превью: {takes_used * 3}/{takes_limit * 3}\n"
                f"Выбери до {hd_limit} 4K — осталось: {hd_rem}\n"
                f"В избранном: {fav_count} (отмечено для 4K: {selected_count})"
            )
        else:
            status_text = (
                f"📸 Ваша фотосессия\n\n"
                f"Осталось снимков: {remaining} из {takes_limit}\n"
                f"4K баланс: {balance['total']}\n"
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


@router.callback_query(F.data.startswith("paywall:"))
async def paywall_buy(callback: CallbackQuery, bot: Bot):
    """User tapped buy on paywall — send Stars invoice."""
    telegram_id = str(callback.from_user.id)
    pack_id = callback.data.split(":", 1)[1]
    if pack_id not in PRODUCT_LADDER_IDS:
        await callback.answer("❌ Пакет недоступен", show_alert=True)
        return
    try:
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
                await callback.answer("Trial уже был использован", show_alert=True)
                return

            pack_name = pack.name
            pack_stars_price = pack.stars_price
            pack_emoji = pack.emoji
            pack_description = pack.description
            pack_takes_limit = getattr(pack, "takes_limit", None)
            pack_hd_amount = getattr(pack, "hd_amount", None)

        with get_db_session() as db:
            audit = AuditService(db)
            audit.log(
                actor_type="user",
                actor_id=telegram_id,
                action="pay_click",
                entity_type="pack",
                entity_id=pack_id,
                payload={"pack_name": pack_name, "stars_price": pack_stars_price, "flow": "paywall"},
            )

        payload = f"session:{pack_id}"
        title = f"{pack_emoji} {pack_name}"
        description = pack_description or f"{pack_takes_limit} снимков + {pack_hd_amount} 4K без watermark"
        prices = [LabeledPrice(label=title, amount=pack_stars_price)]

        await bot.send_invoice(
            chat_id=callback.message.chat.id,
            title=title,
            description=description,
            payload=payload,
            currency="XTR",
            prices=prices,
        )
        await callback.answer()
    except Exception:
        logger.exception("paywall_buy error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("upgrade:"))
async def upgrade_session(callback: CallbackQuery, bot: Bot):
    """Upgrade current session to a better pack."""
    telegram_id = str(callback.from_user.id)
    new_pack_id = callback.data.split(":", 1)[1]
    try:
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
            if not session:
                await callback.answer("❌ Нет активной сессии", show_alert=True)
                return

            old_pack = db.query(Pack).filter(Pack.id == session.pack_id).one_or_none()
            new_pack = db.query(Pack).filter(Pack.id == new_pack_id, Pack.enabled == True).one_or_none()
            if not new_pack:
                await callback.answer("❌ Пакет недоступен", show_alert=True)
                return

            old_price = old_pack.stars_price if old_pack else 0
            upgrade_price = max(0, new_pack.stars_price - old_price)
            new_pack_name = new_pack.name
            session_id = session.id

        with get_db_session() as db:
            audit = AuditService(db)
            audit.log(
                actor_type="user",
                actor_id=telegram_id,
                action="pay_click",
                entity_type="pack",
                entity_id=new_pack_id,
                payload={"pack_name": new_pack_name, "upgrade_price": upgrade_price, "flow": "upgrade", "old_session_id": session_id},
            )

        payload = f"upgrade:{new_pack_id}:{session_id}"
        title = f"⬆️ Апгрейд до {new_pack_name}"
        description = f"Доплата {upgrade_price}⭐ (зачтено {old_price}⭐)"
        prices = [LabeledPrice(label=title, amount=upgrade_price)]

        await bot.send_invoice(
            chat_id=callback.message.chat.id,
            title=title,
            description=description,
            payload=payload,
            currency="XTR",
            prices=prices,
        )
        await callback.answer()
    except Exception:
        logger.exception("upgrade_session error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)


@router.message()
async def unknown_message(message: Message, state: FSMContext):
    """Handle unknown messages (wrong content type in current state)."""
    current = await state.get_state()
    if current == BotStates.waiting_for_audience:
        await message.answer(t("audience.prompt", "Для кого создаём образ?"), reply_markup=audience_keyboard())
    elif current == BotStates.waiting_for_photo:
        await message.answer(t("nav.upload_photo_or_btn", "Отправьте фото или нажмите «🔥 Создать фото»."), reply_markup=main_menu_keyboard())
    elif current == BotStates.waiting_for_trend:
        await message.answer("Выберите тематику и тренд по кнопкам выше.")
    elif current == BotStates.waiting_for_format:
        await message.answer("Выберите формат кадра по кнопкам выше.")
    elif current == BotStates.waiting_for_reference_photo:
        await message.answer(t("flow.send_reference", "Отправьте картинку-образец для копирования стиля."))
    elif current == BotStates.waiting_for_self_photo:
        await message.answer(t("flow.send_your_photo", "Отправьте свою фотографию."))
    elif current == BotStates.waiting_for_self_photo_2:
        await message.answer(t("flow.send_second_photo", "Отправьте вторую фотографию (фото или файл изображения)."))
    elif current == BotStates.waiting_for_prompt:
        await message.answer(t("flow.enter_idea", "Введите текстом описание своей идеи для образа (или выберите тренд по кнопкам)."))
    elif current == BotStates.bank_transfer_waiting_receipt:
        await message.answer("📸 Отправьте скриншот или фото чека перевода.")
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


async def main():
    """Start the bot."""
    logger.info("Starting bot...")
    patch_aiogram_message_methods()
    
    # Initialize bot and dispatcher
    bot = Bot(token=settings.telegram_bot_token)
    
    # Use Redis for FSM storage (persistent states)
    storage = RedisStorage.from_url(settings.redis_url)
    dp = Dispatcher(storage=storage)
    
    # Register error handler
    dp.errors.register(on_error)
    
    # Register security middleware
    dp.message.middleware(SecurityMiddleware())
    dp.callback_query.middleware(SecurityMiddleware())
    # Subscription gate (after /start for new users)
    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware())

    # Register router
    dp.include_router(router)
    runtime_templates.start_listener()
    
    # Delete webhook if exists (we use polling)
    await bot.delete_webhook(drop_pending_updates=True)
    
    logger.info("Bot started successfully!")
    
    # Seed default packs if empty
    try:
        with get_db_session() as db:
            from app.services.payments.service import PaymentService as _PS
            _PS(db).seed_default_packs()
    except Exception:
        logger.warning("Failed to seed default packs on startup")

    try:
        # Start polling (include pre_checkout_query and successful_payment)
        await dp.start_polling(
            bot,
            allowed_updates=[
                "message",
                "callback_query",
                "pre_checkout_query",
            ],
        )
    finally:
        runtime_templates.stop_listener()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
