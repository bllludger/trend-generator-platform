"""Shared helper functions extracted from main.py."""

import asyncio
import logging
import os
from contextlib import contextmanager
from typing import Any, Generator

import redis
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
)
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.user import User
from app.services.telegram_messages.runtime import runtime_templates
from app.utils.telegram_photo import path_for_telegram_photo

from .constants import SUBSCRIPTION_CHANNEL_USERNAME, SUBSCRIPTION_IMAGE_PATH

logger = logging.getLogger("bot")

# ---------------------------------------------------------------------------
# Redis client (rate limiting, etc.)
# ---------------------------------------------------------------------------
redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------
def t(key: str, default: str) -> str:
    return runtime_templates.get(key, default)


def tr(key: str, default: str, **variables: Any) -> str:
    return runtime_templates.render(key, default, **variables)


# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------
def _escape_markdown(s: str) -> str:
    """Экранировать символы для parse_mode='Markdown' (Telegram), чтобы * _ ` [ не ломали разбор."""
    if not s:
        return s
    for char, replacement in (("\\", "\\\\"), ("*", "\\*"), ("_", "\\_"), ("`", "\\`"), ("[", "\\[")):
        s = s.replace(char, replacement)
    return s


def _resolve_trend_example_path(stored_path: str | None, trend_id: str) -> str | None:
    """Резолв пути к файлу примера тренда: сначала сохранённый путь, иначе ищем по trend_examples_dir и шаблону {trend_id}_example.{ext}."""
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


# ---------------------------------------------------------------------------
# Database session
# ---------------------------------------------------------------------------
@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Context manager for database sessions. Handles commit on success and rollback on error."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Aiogram monkey-patching
# ---------------------------------------------------------------------------
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
        try:
            return await original_callback_answer(self, text=text, *args, **kwargs)
        except TelegramBadRequest as e:
            msg = (getattr(e, "message", None) or str(e) or "").lower()
            if "query is too old" in msg or "query id is invalid" in msg:
                # Callback can expire when upstream calls are slow; keep handler flow alive.
                return None
            raise

    Message.answer = _answer
    Message.answer_photo = _answer_photo
    Message.edit_text = _edit_text
    CallbackQuery.answer = _cb_answer
    Message._tm_patched = True


# ---------------------------------------------------------------------------
# /start argument parsers
# ---------------------------------------------------------------------------
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


def _parse_start_theme(text: str | None) -> str | None:
    """Parse /start theme deep link. E.g. '/start theme_uuid' -> 'uuid'."""
    raw = _parse_start_raw_arg(text)
    if raw and raw.startswith("theme_"):
        return raw[6:]
    return None


def _parse_referral_code(text: str | None) -> str | None:
    """Parse /start referral deep link. E.g. '/start ref_ABCD1234' -> 'ABCD1234'."""
    raw = _parse_start_raw_arg(text)
    if raw and raw.startswith("ref_"):
        return raw[4:]
    return None


def _parse_traffic_source(text: str | None) -> tuple[str | None, str | None]:
    """Parse /start ad deep link. Returns (source_slug, campaign) or (None, None)."""
    raw = _parse_start_raw_arg(text)
    if not raw or not raw.startswith("src_"):
        return (None, None)
    rest = raw[4:]
    if not rest:
        return (None, None)
    if "_c_" in rest:
        slug, _, campaign = rest.partition("_c_")
        return (slug, campaign) if slug else (None, None)
    return (rest, None)


# ---------------------------------------------------------------------------
# Document / image helpers
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Message manipulation
# ---------------------------------------------------------------------------
async def _try_delete_messages(bot: Bot, chat_id: int, *message_ids: int) -> None:
    """Мягкое исчезновение: сворачиваем текст в точку, пауза, затем удаление."""
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


def _edit_message_text_or_caption(msg: Message, text: str, parse_mode: str = "HTML", reply_markup=None):
    """Edit message text or caption. Use edit_caption when message has photo (no text)."""
    if msg.photo:
        return msg.edit_caption(caption=text, parse_mode=parse_mode, reply_markup=reply_markup)
    if msg.text is not None:
        return msg.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    if msg.caption is not None:
        return msg.edit_caption(caption=text, parse_mode=parse_mode, reply_markup=reply_markup)
    return msg.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)


# ---------------------------------------------------------------------------
# Chat type / subscription checks
# ---------------------------------------------------------------------------
def _is_private_chat(event: TelegramObject) -> bool:
    """True если апдейт из личного чата (не группа/канал)."""
    if isinstance(event, Message) and event.chat:
        return (getattr(event.chat, "type", None) or "") == "private"
    if hasattr(event, "message") and event.message and getattr(event.message, "chat", None):
        return (getattr(event.message.chat, "type", None) or "") == "private"
    return True


def _has_paid_profile(
    user: "User | None",
    active_session: "SessionModel | None" = None,
) -> bool:
    """True only for users with an active paid session."""
    if not user or not active_session:
        return False
    pack_id_norm = str(active_session.pack_id or "").strip().lower()
    if pack_id_norm in {"free_preview", "trial"}:
        return False
    return True


def _user_subscribed(user: User) -> bool:
    """Проверка: пользователь уже прошёл подписку на канал (флаг в flags)."""
    if not SUBSCRIPTION_CHANNEL_USERNAME:
        return True
    return bool((user.flags or {}).get("subscribed_examples_channel"))


async def _send_subscription_prompt(target: Message, subscription_text: str, kb: InlineKeyboardMarkup | None) -> None:
    """Отправить экран «Подпишитесь на канал»: картинка с подписью или только текст + клавиатура."""
    if os.path.exists(SUBSCRIPTION_IMAGE_PATH):
        try:
            photo_path, is_temp = path_for_telegram_photo(SUBSCRIPTION_IMAGE_PATH)
            await target.answer_photo(
                photo=FSInputFile(photo_path),
                caption=subscription_text,
                reply_markup=kb,
            )
            if is_temp and os.path.isfile(photo_path):
                try:
                    os.unlink(photo_path)
                except OSError:
                    pass
        except Exception as e:
            logger.warning("subscription_photo_failed", extra={"path": SUBSCRIPTION_IMAGE_PATH, "error": str(e)})
            await target.answer(subscription_text, reply_markup=kb)
    else:
        await target.answer(subscription_text, reply_markup=kb)
