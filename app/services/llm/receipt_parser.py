"""
Receipt parser: распознаёт данные банковского чека из скриншота/фото.

Vision возвращает JSON с полями: amount_rub, card_number, date_time, comment.
Парсер извлекает значения, валидирует каждое поле regex'ами (сумма, карта, дата);
результат сверяется с ожиданиями заявки (expected_rub, карта, комментарий).
"""
import base64
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

from app.core.config import settings

logger = logging.getLogger("llm.receipt_parser")

# ---------------------------------------------------------------------------
# Дефолтные промпты: ответ только в формате JSON
# ---------------------------------------------------------------------------
DEFAULT_SYSTEM_PROMPT = (
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
DEFAULT_USER_PROMPT = (
    "На изображении чек или подтверждение банковского перевода. "
    "Извлеки и верни в формате JSON: 1) сумму в рублях (число), "
    "2) номер карты получателя как на чеке, "
    "3) дату и время перевода (ДД.ММ.ГГГГ ЧЧ:ММ), "
    "4) комментарий к переводу. "
    "Если поля нет — пиши NOT_FOUND для этого ключа."
)

# ---------------------------------------------------------------------------
# Regex-паттерны
# ---------------------------------------------------------------------------

# Сумма (рубли с копейками)
AMOUNT_REGEX_PATTERN = r"(\d[\d\s]*[\d](?:[.,]\d{1,2})?)"
_AMOUNT_RE = re.compile(AMOUNT_REGEX_PATTERN)

# Карта получателя: форматы 220424******5005, 2204 24** **** 5005, 2204****5005 и т.п.
CARD_REGEX_PATTERN = r"(\d{4})\d{0,2}\s*\*{2,}\s*(\d{4})"
_CARD_RE = re.compile(CARD_REGEX_PATTERN)

# Дата/время перевода: ДД.ММ.ГГГГ ЧЧ:ММ(:СС)
RECEIPT_DT_REGEX_PATTERN = r"(\d{2})[./](\d{2})[./](\d{4})\s+(\d{2}):(\d{2})(?::(\d{2}))?"
_RECEIPT_DT_RE = re.compile(RECEIPT_DT_REGEX_PATTERN)


# ---------------------------------------------------------------------------
# Внутренние парсеры
# ---------------------------------------------------------------------------

def _get_mime_type(path: str) -> str:
    ext = Path(path).suffix.lower().lstrip(".")
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    }.get(ext, "image/jpeg")


def _parse_amount_from_text(text: str) -> float | None:
    cleaned = text.strip()
    if not cleaned or "NOT_FOUND" in cleaned.upper():
        return None
    match = _AMOUNT_RE.search(cleaned)
    if not match:
        return None
    raw = match.group(1).replace(" ", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_card_from_text(text: str) -> tuple[str | None, str | None]:
    """Извлечь first4 и last4 цифры карты получателя из текста."""
    if not text or "NOT_FOUND" in text.upper():
        return None, None
    m = _CARD_RE.search(text)
    if m:
        return m.group(1), m.group(2)
    return None, None


def _parse_receipt_datetime(text: str) -> datetime | None:
    """Извлечь дату/время перевода из текста (ДД.ММ.ГГГГ ЧЧ:ММ)."""
    if not text or "NOT_FOUND" in text.upper():
        return None
    m = _RECEIPT_DT_RE.search(text)
    if not m:
        return None
    try:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hour, minute = int(m.group(4)), int(m.group(5))
        sec = int(m.group(6)) if m.group(6) else 0
        # Предполагаем часовой пояс Москва (+3) для банковских чеков
        from datetime import timedelta
        tz_msk = timezone(timedelta(hours=3))
        return datetime(year, month, day, hour, minute, sec, tzinfo=tz_msk)
    except (ValueError, OverflowError):
        return None


def _parse_comment_from_text(text: str) -> str | None:
    """Извлечь комментарий к переводу (4-я строка ответа Vision или поле comment в JSON)."""
    if not text:
        return None
    if text.strip().upper() == "NOT_FOUND":
        return None
    return text.strip() or None


def _extract_json_from_response(raw: str) -> dict[str, str] | None:
    """
    Из ответа Vision извлечь JSON-объект с полями amount_rub, card_number, date_time, comment.
    Поддерживает обёртку в ```json ... ``` и голый JSON.
    """
    text = raw.strip()
    # Убрать markdown блок
    if "```" in text:
        start = text.find("```")
        if start != -1:
            rest = text[start + 3:]
            if rest.lower().startswith("json"):
                rest = rest[4:].lstrip()
            end = rest.find("```")
            if end != -1:
                text = rest[:end].strip()
            else:
                text = rest.strip()
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        return {
            "amount_rub": _str_field(data, "amount_rub"),
            "card_number": _str_field(data, "card_number"),
            "date_time": _str_field(data, "date_time"),
            "comment": _str_field(data, "comment"),
        }
    except (json.JSONDecodeError, TypeError):
        return None


def _str_field(obj: dict, key: str) -> str:
    v = obj.get(key)
    if v is None:
        return "NOT_FOUND"
    if isinstance(v, (int, float)):
        return str(v)
    return str(v).strip()


def compute_receipt_fingerprint(
    amount_rub: float | None,
    card_first4: str | None,
    card_last4: str | None,
    receipt_dt: datetime | None,
    file_path: str | None = None,
) -> str | None:
    """SHA-256 отпечаток чека для обнаружения дубликатов."""
    parts: list[str] = []
    if amount_rub is not None:
        parts.append(f"amount={amount_rub:.2f}")
    if card_first4 and card_last4:
        parts.append(f"card={card_first4}****{card_last4}")
    if receipt_dt:
        parts.append(f"dt={receipt_dt.strftime('%Y%m%d%H%M')}")
    if not parts:
        # Fallback: хеш файла
        if file_path and Path(file_path).exists():
            with open(file_path, "rb") as f:
                return hashlib.sha256(f.read(1024 * 256)).hexdigest()[:32]
        return None
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Основная функция
# ---------------------------------------------------------------------------

def analyze_receipt(image_path: str, config: dict[str, Any] | None = None) -> dict:
    """
    Распознать данные перевода из изображения чека.

    Returns dict с ключами:
        amount_rub, raw_response, regex_pattern, vision_model,
        card_first4, card_last4, receipt_dt, comment, receipt_fingerprint
    """
    _empty = {
        "amount_rub": None,
        "raw_response": "",
        "regex_pattern": AMOUNT_REGEX_PATTERN,
        "card_first4": None,
        "card_last4": None,
        "receipt_dt": None,
        "comment": None,
        "receipt_fingerprint": None,
    }

    path = Path(image_path)
    if not path.exists():
        logger.error("receipt_file_not_found", extra={"path": image_path})
        return {**_empty, "raw_response": "FILE_NOT_FOUND"}

    cfg = config or {}
    system_prompt = cfg.get("system_prompt") or DEFAULT_SYSTEM_PROMPT
    user_prompt = cfg.get("user_prompt") or DEFAULT_USER_PROMPT
    model = cfg.get("model") or getattr(settings, "openai_vision_model", "gpt-4o")

    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    mime = _get_mime_type(str(path))
    client = OpenAI(api_key=settings.openai_api_key)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    ],
                },
            ],
            max_completion_tokens=350,
        )
    except TypeError:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    ],
                },
            ],
            max_tokens=350,
        )
    except Exception as e:
        logger.exception("receipt_vision_api_error", extra={"path": image_path})
        return {**_empty, "raw_response": f"API_ERROR: {e}"}

    raw = (response.choices[0].message.content or "").strip()

    # Сначала пробуем распарсить как JSON (формат: amount_rub, card_number, date_time, comment)
    json_data = _extract_json_from_response(raw)
    if json_data:
        amount = _parse_amount_from_text(json_data["amount_rub"])
        card_first4, card_last4 = _parse_card_from_text(json_data["card_number"])
        receipt_dt = _parse_receipt_datetime(json_data["date_time"])
        comment = _parse_comment_from_text(json_data["comment"])
    else:
        # Fallback: ответ на 4 строках (старый формат)
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        line0 = lines[0] if len(lines) > 0 else ""
        line1 = lines[1] if len(lines) > 1 else ""
        line2 = lines[2] if len(lines) > 2 else ""
        line3 = lines[3] if len(lines) > 3 else ""
        amount = _parse_amount_from_text(line0)
        card_first4, card_last4 = _parse_card_from_text(line1)
        receipt_dt = _parse_receipt_datetime(line2)
        comment = _parse_comment_from_text(line3)

    fingerprint = compute_receipt_fingerprint(amount, card_first4, card_last4, receipt_dt, image_path)

    logger.info(
        "receipt_analyzed",
        extra={
            "path": image_path,
            "raw": raw,
            "amount_rub": amount,
            "card": f"{card_first4}****{card_last4}" if card_first4 else None,
            "receipt_dt": receipt_dt.isoformat() if receipt_dt else None,
            "comment": comment,
        },
    )

    return {
        "amount_rub": amount,
        "raw_response": raw,
        "regex_pattern": AMOUNT_REGEX_PATTERN,
        "vision_model": model,
        "card_first4": card_first4,
        "card_last4": card_last4,
        "receipt_dt": receipt_dt,
        "comment": comment,
        "receipt_fingerprint": fingerprint,
    }


def amounts_match(
    actual: float | None,
    expected: float,
    tolerance_abs: float = 1.0,
    tolerance_pct: float = 0.02,
) -> bool:
    """Проверить совпадение суммы с допуском. Допуски можно передать из конфига БД."""
    if actual is None:
        return False
    diff = abs(actual - expected)
    tolerance = max(tolerance_abs, expected * tolerance_pct)
    return diff <= tolerance
