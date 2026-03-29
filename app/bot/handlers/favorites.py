import logging
import os
from datetime import datetime, timezone
from typing import Any

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from sqlalchemy.orm import Session

from app.bot.states import BotStates
from app.bot.helpers import t, tr, get_db_session, _escape_markdown, logger
from app.bot.keyboards import main_menu_keyboard
from app.core.config import settings
from app.services.users.service import UserService
from app.services.sessions.service import SessionService
from app.services.takes.service import TakeService
from app.services.favorites.service import FavoriteService
from app.services.hd_balance.service import HDBalanceService
from app.services.audit.service import AuditService
from app.services.product_analytics.service import ProductAnalyticsService
from app.services.compensations.service import CompensationService
from app.services.unlock_order.service import UnlockOrderService, unlock_photo_display_filename
from app.models.user import User
from app.models.take import Take as TakeModel
from app.models.trend import Trend as TrendModel
from app.models.session import Session as SessionModel

favorites_router = Router()


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
        trend_label = "Фото"
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
        trend_label = fav.get("trend_label") or "Фото"
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

    # В пользовательском UI только счётчик фото; 4K не показываем отдельной строкой (терминология NeoBanana)

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


def _select_hd_favorites_with_bundle_budget(
    db: Session,
    favorites: list[Any],
    hd_balance_total: int,
) -> list[str]:
    """
    Pick favorites for HD delivery using "1 credit per take bundle" rule.
    All variants from the same take are deliverable after a single charge.
    """
    if hd_balance_total <= 0 or not favorites:
        return []

    take_ids = [str(getattr(f, "take_id", "")) for f in favorites if getattr(f, "take_id", None)]
    takes = (
        db.query(TakeModel)
        .filter(TakeModel.id.in_(take_ids))
        .all()
        if take_ids
        else []
    )
    charged_by_take = {str(t.id): bool(getattr(t, "hd_bundle_charged", False)) for t in takes}

    remaining_budget = hd_balance_total
    reserved_takes: set[str] = set()
    selected_ids: list[str] = []

    for fav in favorites:
        take_id = str(getattr(fav, "take_id", "") or "")
        if not take_id:
            continue
        already_charged = charged_by_take.get(take_id, False) or (take_id in reserved_takes)
        if already_charged:
            selected_ids.append(str(fav.id))
            continue
        if remaining_budget <= 0:
            continue
        remaining_budget -= 1
        reserved_takes.add(take_id)
        selected_ids.append(str(fav.id))

    return selected_ids


@favorites_router.callback_query(F.data == "open_favorites")
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
            ProductAnalyticsService(db).track(
                "button_click",
                user.id,
                properties={"button_id": "open_favorites"},
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


@favorites_router.callback_query(F.data == "favorites_clear_all")
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
            try:
                ProductAnalyticsService(db).track("button_click", user.id, properties={"button_id": "favorites_clear_all"})
            except Exception:
                logger.exception("button_click track failed favorites_clear_all")
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


@favorites_router.callback_query(F.data.startswith("remove_fav:"))
async def remove_favorite(callback: CallbackQuery, state: FSMContext):
    """Remove a favorite."""
    telegram_id = str(callback.from_user.id)
    fav_id = callback.data.split(":", 1)[1]
    try:
        with get_db_session() as db:
            user = UserService(db).get_by_telegram_id(telegram_id)
            if user:
                try:
                    ProductAnalyticsService(db).track(
                        "button_click",
                        user.id,
                        properties={"button_id": "remove_fav", "favorite_id": fav_id},
                    )
                except Exception:
                    logger.exception("button_click track failed remove_fav")
            fav_svc = FavoriteService(db)
            removed = fav_svc.remove_favorite_for_user(user.id, fav_id) if user else False
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


@favorites_router.callback_query(F.data.startswith("select_hd:"))
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
            try:
                ProductAnalyticsService(db).track(
                    "button_click",
                    user.id,
                    properties={"button_id": "select_hd", "favorite_id": fav_id},
                )
            except Exception:
                logger.exception("button_click track failed select_hd")
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


@favorites_router.callback_query(F.data.startswith("deselect_hd:"))
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
            try:
                ProductAnalyticsService(db).track(
                    "button_click",
                    user.id,
                    properties={"button_id": "deselect_hd", "favorite_id": fav_id},
                )
            except Exception:
                logger.exception("button_click track failed deselect_hd")
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


@favorites_router.callback_query(F.data.startswith("hd_problem:"))
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
            try:
                ProductAnalyticsService(db).track(
                    "button_click",
                    user.id,
                    properties={"button_id": "hd_problem", "favorite_id": fav_id},
                )
            except Exception:
                logger.exception("button_click track failed hd_problem")
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


@favorites_router.callback_query(F.data == "deliver_hd_album")
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
            selected_ids = _select_hd_favorites_with_bundle_budget(
                db,
                selected,
                int(balance.get("total", 0) or 0),
            )
            if not selected_ids:
                await callback.answer("❌ Недостаточно доступа. Купите пакет.", show_alert=True)
                return

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


@favorites_router.callback_query(F.data.startswith("unlock_resend:"))
async def unlock_resend_callback(callback: CallbackQuery):
    """Получить фото снова (уже оплаченный unlock order)."""
    telegram_id = str(callback.from_user.id)
    parts = callback.data.split(":", 1)
    if len(parts) != 2:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    order_id = (parts[1] or "").strip()
    if not order_id:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    try:
        with get_db_session() as db:
            unlock_svc = UnlockOrderService(db)
            order = unlock_svc.get_by_id(order_id)
            if not order or str(order.telegram_user_id) != telegram_id:
                await callback.answer("Заказ не найден", show_alert=True)
                return
            if order.status not in ("paid", "delivered", "delivery_failed"):
                await callback.answer("Заказ ещё не оплачен", show_alert=True)
                return
            user = UserService(db).get_by_telegram_id(telegram_id)
            if user:
                try:
                    ProductAnalyticsService(db).track(
                        "button_click",
                        user.id,
                        properties={"button_id": "unlock_resend", "order_id": order_id},
                    )
                except Exception:
                    logger.exception("button_click track failed unlock_resend")
            take = TakeService(db).get_take(order.take_id)
            if not take:
                await callback.answer("Фото не найдено", show_alert=True)
                return
            _, original_path = TakeService(db).get_variant_paths(take, order.variant)
            if not original_path or not os.path.exists(original_path):
                await callback.answer("Файл недоступен", show_alert=True)
                return
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
                    filename=unlock_photo_display_filename(order.id, original_path),
                )
            finally:
                tg.close()
        await callback.answer("Фото отправлено")
        await callback.message.answer("Фото отправлено в чат.")
    except Exception:
        logger.exception("unlock_resend_callback error", extra={"user_id": telegram_id})
        await callback.answer("❌ Ошибка", show_alert=True)
