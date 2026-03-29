import logging
import os
import re
import random
import string
from datetime import datetime, timezone
from uuid import uuid4

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy.orm import Session

from app.bot.states import BotStates
from app.bot.helpers import t, tr, get_db_session, redis_client, logger
from app.bot.keyboards import main_menu_keyboard
from app.core.config import settings
from app.services.users.service import UserService
from app.services.sessions.service import SessionService
from app.services.payments.service import PaymentService, PRODUCT_LADDER_IDS
from app.services.audit.service import AuditService
from app.services.product_analytics.service import ProductAnalyticsService
from app.services.bank_transfer.settings_service import BankTransferSettingsService
from app.services.trial_v2.service import TrialV2Service
from app.services.balance_tariffs import get_balance_line
from app.models.user import User
from app.models.bank_transfer_receipt_log import BankTransferReceiptLog

bank_transfer_router = Router()


@bank_transfer_router.callback_query(F.data == "bank_transfer:start")
async def bank_transfer_start(callback: CallbackQuery, state: FSMContext):
    """Legacy callback: перевод на карту отключен, оставляем редирект в ЮMoney."""
    await state.clear()
    await callback.answer("Оплата переводом отключена. Доступна только ЮMoney.", show_alert=True)
    try:
        await callback.message.answer(
            "Откройте магазин и выберите пакет для оплаты через ЮMoney.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🛒 Открыть магазин", callback_data="shop:open")],
                [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
            ]),
        )
    except Exception:
        logger.exception("bank_transfer_start redirect failed")


def _generate_receipt_code() -> str:
    """Сгенерировать уникальный номер «оплата № N» через Redis-счётчик."""
    try:
        num = redis_client.incr("bank_transfer:receipt_code_seq")
    except Exception:
        import random
        num = random.randint(1000, 999999)
    return f"оплата № {num}"


@bank_transfer_router.callback_query(F.data.startswith("bank_pack:"))
async def bank_pack_selected(callback: CallbackQuery, state: FSMContext):
    """Legacy callback: перевод на карту отключен, оставляем редирект в ЮMoney."""
    from app.bot.keyboards import _payment_method_keyboard

    await state.clear()
    pack_id = callback.data.split(":", 1)[1]
    await callback.answer("Оплата переводом отключена. Доступна только ЮMoney.", show_alert=True)
    try:
        if pack_id in PRODUCT_LADDER_IDS:
            await callback.message.answer(
                "Выберите оплату через ЮMoney.",
                reply_markup=_payment_method_keyboard(pack_id),
            )
        else:
            await callback.message.answer(
                "Откройте магазин и выберите пакет для оплаты через ЮMoney.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🛒 Открыть магазин", callback_data="shop:open")],
                    [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
                ]),
            )
    except Exception:
        logger.exception("bank_pack_selected redirect failed")


@bank_transfer_router.callback_query(F.data == "bank_transfer:cancel")
async def bank_transfer_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена оплаты переводом."""
    telegram_id = str(callback.from_user.id) if callback.from_user else None
    if telegram_id:
        try:
            with get_db_session() as db:
                user = UserService(db).get_by_telegram_id(telegram_id)
                if user:
                    ProductAnalyticsService(db).track("button_click", user.id, properties={"button_id": "bank_transfer_cancel"})
        except Exception:
            logger.exception("button_click track failed bank_transfer_cancel")
    await state.clear()
    await callback.message.answer(
        "Оплата отменена. Откройте магазин для оплаты через ЮMoney.",
        reply_markup=main_menu_keyboard(),
    )
    await callback.answer()


@bank_transfer_router.callback_query(F.data == "bank_transfer:retry")
async def bank_transfer_retry(callback: CallbackQuery, state: FSMContext):
    """Legacy callback: повтор перевода отключен, оставляем редирект в ЮMoney."""
    await state.clear()
    await callback.answer("Оплата переводом отключена. Доступна только ЮMoney.", show_alert=True)
    try:
        await callback.message.answer(
            "Откройте магазин и выберите пакет для оплаты через ЮMoney.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🛒 Открыть магазин", callback_data="shop:open")],
                [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
            ]),
        )
    except Exception:
        logger.exception("bank_transfer_retry redirect failed")


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
    analytics_session_id = data.get("bank_analytics_session_id")
    expected_receipt_code = data.get("bank_receipt_code", "")
    telegram_id = str(message.from_user.id)

    if expected_rub is None or not pack_id or tokens is None or stars is None:
        await state.clear()
        await message.answer("Сессия истекла. Начните оплату заново в магазине.", reply_markup=main_menu_keyboard())
        return

    # --- Rate limit (6.4) ---
    if not _check_receipt_rate_limit(telegram_id):
        with get_db_session() as db:
            _create_receipt_log(
                db,
                telegram_user_id=telegram_id,
                file_path=file_path,
                raw_vision_response="",
                regex_pattern="",
                extracted_amount_rub=None,
                expected_rub=float(expected_rub),
                match_success=False,
                pack_id=pack_id,
                rejection_reason="rate_limited",
            )
            db.commit()
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
            is_session_pack = pack_id in PRODUCT_LADDER_IDS
            session_balance_line: str | None = None
            session_takes_limit: int | None = None

            with get_db_session() as db:
                payment_service = PaymentService(db)
                if is_session_pack:
                    payment, session, trial_error, attached_free_takes = payment_service.process_session_purchase_bank_transfer(
                        telegram_user_id=telegram_id,
                        pack_id=pack_id,
                        amount_rub=float(amount),
                        reference=reference,
                        analytics_session_id=analytics_session_id,
                    )
                    if trial_error == "trial_already_used":
                        db.rollback()
                        with get_db_session() as db_log:
                            _create_receipt_log(
                                db_log,
                                telegram_user_id=telegram_id,
                                file_path=file_path,
                                match_success=False,
                                rejection_reason="trial_already_used",
                                **log_kwargs,
                            )
                            db_log.commit()
                        await state.clear()
                        await wait_msg.edit_text(
                            f"Пробный пакет уже был использован. Обратитесь в поддержку: @{settings.support_username} — мы вернём средства на карту.",
                            parse_mode="Markdown",
                        )
                        logger.warning(
                            "bank_transfer_trial_already_used",
                            extra={"user_id": telegram_id, "pack_id": pack_id},
                        )
                        return
                    if payment:
                        payment_id_created = payment.id
                    if session:
                        if attached_free_takes and attached_free_takes > 0:
                            remaining_display = session.takes_limit
                            session_balance_line = f"Осталось фото: {remaining_display} из {session.takes_limit}"
                        else:
                            session_balance_line = get_balance_line(db, telegram_id)
                        session_takes_limit = session.takes_limit
                else:
                    payment = payment_service.credit_tokens_manual(
                        telegram_user_id=telegram_id,
                        pack_id=pack_id,
                        stars_amount=stars,
                        tokens_granted=tokens,
                        reference=reference,
                    )
                    if payment:
                        payment_id_created = payment.id
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
            if is_session_pack and session_balance_line is not None and session_takes_limit is not None:
                success_text = effective["success_message"].format(
                    pack_name=pack_name,
                    tokens=session_takes_limit,
                    balance=session_balance_line,
                )
            else:
                user = None
                with get_db_session() as db:
                    user = db.query(User).filter(User.telegram_id == telegram_id).one_or_none()
                balance = user.token_balance if user else tokens
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
                    f"Обратитесь в поддержку: @{settings.support_username} — укажите время перевода и приложите чек, мы проверим вручную.\n\n"
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


@bank_transfer_router.message(BotStates.bank_transfer_waiting_receipt, F.photo)
async def bank_receipt_photo(message: Message, state: FSMContext, bot: Bot):
    """Приём чека как фото."""
    telegram_id = str(message.from_user.id) if message.from_user else None
    if telegram_id:
        try:
            with get_db_session() as db:
                user = UserService(db).get_by_telegram_id(telegram_id)
                if user:
                    ProductAnalyticsService(db).track(
                        "bank_receipt_uploaded",
                        user.id,
                        properties={"button_id": "bank_receipt_uploaded", "type": "photo"},
                    )
        except Exception:
            logger.exception("bank_receipt_uploaded track failed")
    await state.clear()
    await message.answer(
        "Оплата переводом отключена. Откройте магазин и оплатите через ЮMoney.",
        reply_markup=main_menu_keyboard(),
    )


@bank_transfer_router.message(BotStates.bank_transfer_waiting_receipt, F.document)
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

    telegram_id = str(message.from_user.id) if message.from_user else None
    if telegram_id:
        try:
            with get_db_session() as db:
                user = UserService(db).get_by_telegram_id(telegram_id)
                if user:
                    ProductAnalyticsService(db).track(
                        "bank_receipt_uploaded",
                        user.id,
                        properties={"button_id": "bank_receipt_uploaded", "type": "document"},
                    )
        except Exception:
            logger.exception("bank_receipt_uploaded track failed")
    await state.clear()
    await message.answer(
        "Оплата переводом отключена. Откройте магазин и оплатите через ЮMoney.",
        reply_markup=main_menu_keyboard(),
    )


@bank_transfer_router.message(BotStates.bank_transfer_waiting_receipt)
async def bank_receipt_wrong_input(message: Message):
    """Неверный ввод в отключенном состоянии bank transfer."""
    await message.answer(
        "Оплата переводом отключена. Откройте магазин и оплатите через ЮMoney.",
        reply_markup=main_menu_keyboard(),
    )
