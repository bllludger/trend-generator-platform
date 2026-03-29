"""Сервис настроек оплаты переводом на карту (реквизиты, промпты, допуски)."""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.bank_transfer_settings import BankTransferSettings


# Дефолты: Vision возвращает JSON с полями amount_rub, card_number, date_time, comment
DEFAULT_RECEIPT_SYSTEM = (
    "Ты — система распознавания банковских чеков и подтверждений переводов. "
    "Из изображения извлеки данные и верни ТОЛЬКО один валидный JSON-объект без markdown и пояснений.\n"
    "Ключи JSON:\n"
    "  amount_rub — сумма перевода в рублях (число или строка, например 150.00).\n"
    "  card_number — номер карты получателя как на чеке (например 220424******5005).\n"
    "  date_time — дата и время перевода в формате ДД.ММ.ГГГГ ЧЧ:ММ (например 12.02.2026 23:36).\n"
    "  comment — текст комментария к переводу.\n"
    "Если поля на изображении нет — укажи для него значение NOT_FOUND.\n"
    "Пример ответа:\n"
    '{"amount_rub": "150.00", "card_number": "220424******5005", "date_time": "12.02.2026 23:36", "comment": "оплата № 131"}'
)
DEFAULT_RECEIPT_USER = (
    "На изображении чек или подтверждение банковского перевода. "
    "Извлеки и верни в формате JSON: 1) сумму в рублях (число), "
    "2) номер карты получателя как на чеке, "
    "3) дату и время перевода (ДД.ММ.ГГГГ ЧЧ:ММ), "
    "4) комментарий к переводу. "
    "Если поля нет — пиши NOT_FOUND для этого ключа."
)
DEFAULT_STEP1 = (
    "💵 *Оплата переводом на карту*\n\n"
    "Если вы не знаете, как купить Telegram Stars — можно оплатить переводом "
    "на карту Озон Банка. Мы проверим чек и зачислим фото на баланс автоматически.\n\n"
    "Выберите пакет:"
)
DEFAULT_STEP2 = (
    "💵 *Оплата: {pack_name}*\n\n"
    "📦 Пакет: *{tokens}* фото\n"
    "💰 Сумма к переводу: *{expected_rub} ₽*\n\n"
    "🏦 Номер карты: `{card}`\n{comment_line}\n"
    "📝 В комментарии к переводу укажите: *{receipt_code}*\n\n"
    "⚠️ *После перевода отправьте чек (скриншот или фото).* Без чека оплата не засчитывается.\n\n"
    "Мы проверим сумму, номер карты, комментарий и дату перевода — при совпадении зачислим фото на баланс."
)
DEFAULT_SUCCESS = (
    "✅ *Оплата засчитана!*\n\n"
    "Пакет: *{pack_name}*\n"
    "Начислено: *{tokens}* фото\n"
    "Ваш баланс: *{balance}* фото\n\n"
    "Теперь ваши фото будут без водяного знака!"
)
DEFAULT_MISMATCH = (
    "❌ *Не удалось подтвердить оплату.*\n\n"
    "Отправьте чек ещё раз (скриншот или фото перевода).\n"
    "Убедитесь, что на скриншоте видны: сумма перевода, номер карты получателя, комментарий к переводу и дата. Чек не должен быть старше 48 часов."
)


class BankTransferSettingsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self) -> BankTransferSettings | None:
        return self.db.query(BankTransferSettings).filter(BankTransferSettings.id == 1).first()

    def get_or_create(self) -> BankTransferSettings:
        row = self.get()
        if row:
            return row
        row = BankTransferSettings(id=1)
        self.db.add(row)
        self.db.flush()
        return row

    def is_enabled(self) -> bool:
        row = self.get()
        if not row:
            return False
        return bool(row.enabled and (row.card_number or "").strip())

    def get_effective(self) -> dict[str, Any]:
        """Настройки для бота: реквизиты и тексты."""
        row = self.get_or_create()
        return {
            "enabled": row.enabled and bool((row.card_number or "").strip()),
            "card_number": (row.card_number or "").strip(),
            "comment": (row.comment or "").strip(),
            "step1_description": (row.step1_description or "").strip() or DEFAULT_STEP1,
            "step2_requisites": (row.step2_requisites or "").strip() or DEFAULT_STEP2,
            "success_message": (row.success_message or "").strip() or DEFAULT_SUCCESS,
            "amount_mismatch_message": (row.amount_mismatch_message or "").strip() or DEFAULT_MISMATCH,
        }

    def get_receipt_config(self) -> dict[str, Any]:
        """Конфиг для парсера чека (Vision): промпты, модель, допуски."""
        row = self.get_or_create()
        return {
            "system_prompt": (row.receipt_system_prompt or "").strip() or DEFAULT_RECEIPT_SYSTEM,
            "user_prompt": (row.receipt_user_prompt or "").strip() or DEFAULT_RECEIPT_USER,
            "model": (row.receipt_vision_model or "").strip() or "gpt-4o",
            "amount_tolerance_abs": float(row.amount_tolerance_abs) if row.amount_tolerance_abs is not None else 1.0,
            "amount_tolerance_pct": float(row.amount_tolerance_pct) if row.amount_tolerance_pct is not None else 0.02,
        }

    def _mask_card(self, card: str) -> str:
        if not (card or "").strip():
            return ""
        digits = "".join(c for c in card if c.isdigit())
        if len(digits) >= 4:
            return "•••• •••• •••• " + digits[-4:]
        return "•••• (настроено)"

    def as_dict(self, mask_card: bool = True) -> dict[str, Any]:
        """Для API GET: эффективные значения (при пустом в БД — дефолты). Админка всегда видит то, что реально используется."""
        row = self.get_or_create()
        card = row.card_number or ""
        return {
            "enabled": row.enabled and bool(card.strip()),
            "card_number": self._mask_card(card) if mask_card else card,
            "card_masked": self._mask_card(card),
            "comment": row.comment or "",
            "receipt_system_prompt": (row.receipt_system_prompt or "").strip() or DEFAULT_RECEIPT_SYSTEM,
            "receipt_user_prompt": (row.receipt_user_prompt or "").strip() or DEFAULT_RECEIPT_USER,
            "receipt_vision_model": (row.receipt_vision_model or "").strip() or "gpt-4o",
            "amount_tolerance_abs": float(row.amount_tolerance_abs) if row.amount_tolerance_abs is not None else 1.0,
            "amount_tolerance_pct": float(row.amount_tolerance_pct) if row.amount_tolerance_pct is not None else 0.02,
            "step1_description": (row.step1_description or "").strip() or DEFAULT_STEP1,
            "step2_requisites": (row.step2_requisites or "").strip() or DEFAULT_STEP2,
            "success_message": (row.success_message or "").strip() or DEFAULT_SUCCESS,
            "amount_mismatch_message": (row.amount_mismatch_message or "").strip() or DEFAULT_MISMATCH,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def update(self, data: dict[str, Any]) -> dict[str, Any]:
        """Обновить настройки из админки."""
        row = self.get_or_create()
        if "enabled" in data:
            row.enabled = bool(data["enabled"])
        if "card_number" in data:
            row.card_number = str(data["card_number"])[:32]
        if "comment" in data:
            row.comment = str(data["comment"])
        if "receipt_system_prompt" in data:
            row.receipt_system_prompt = str(data["receipt_system_prompt"])
        if "receipt_user_prompt" in data:
            row.receipt_user_prompt = str(data["receipt_user_prompt"])
        if "receipt_vision_model" in data:
            row.receipt_vision_model = str(data["receipt_vision_model"])[:64]
        if "amount_tolerance_abs" in data and data["amount_tolerance_abs"] is not None:
            row.amount_tolerance_abs = float(data["amount_tolerance_abs"])
        if "amount_tolerance_pct" in data and data["amount_tolerance_pct"] is not None:
            row.amount_tolerance_pct = float(data["amount_tolerance_pct"])
        if "step1_description" in data:
            row.step1_description = str(data["step1_description"])
        if "step2_requisites" in data:
            row.step2_requisites = str(data["step2_requisites"])
        if "success_message" in data:
            row.success_message = str(data["success_message"])
        if "amount_mismatch_message" in data:
            row.amount_mismatch_message = str(data["amount_mismatch_message"])
        row.updated_at = datetime.now(timezone.utc)
        self.db.add(row)
        self.db.flush()
        return self.as_dict(mask_card=True)
