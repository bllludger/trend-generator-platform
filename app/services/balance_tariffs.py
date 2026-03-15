"""
Шаблон «Баланс + Выбор пакета» (outcome-first).
Один экран магазина: пакеты фото, один счётчик «Осталось фото».
Порядок: Neo Start → Neo Pro → Neo Unlimited → Пробный (последний, только если trial_purchased=false).
"""
from __future__ import annotations

from app.models.pack import Pack
from app.services.payments.service import PaymentService, PRODUCT_LADDER_IDS
from app.services.sessions.service import SessionService
from app.services.users.service import UserService

DISPLAY_ORDER = ("neo_start", "neo_pro", "neo_unlimited", "trial")

# Для кнопок: имя без эмодзи (эмодзи берём из pack.emoji). Без слова «Trial» — нейтральное «Пробный».
SHORT_NAMES = {
    "trial": "Пробный",
    "neo_start": "Neo Start",
    "neo_pro": "Neo Pro (Хит)",
    "neo_unlimited": "Neo Unlimited",
}

# Цены в рублях для отображения на кнопках оплаты (инлайн)
DISPLAY_RUB = {
    "trial": 129,
    "neo_start": 199,
    "neo_pro": 699,
    "neo_unlimited": 1990,
}


def _pack_outcome_label(pack: Pack) -> str:
    """Короткие outcome-подписи для кнопок."""
    if pack.id == "trial":
        return "1 фото для пробы"
    if pack.id == "neo_start":
        return "10 фото"
    if pack.id == "neo_pro":
        return "40 фото"
    if pack.id == "neo_unlimited":
        return "120 фото"
    return pack.description or ""


def _pack_text_line(pack: Pack) -> str:
    """Строка описания пакета в тексте сообщения (без цены)."""
    if pack.id == "trial":
        return "1 фото — попробовать одно удачное фото."
    if pack.id == "neo_start":
        return "Neo Start — 10 фото (для старта)"
    if pack.id == "neo_pro":
        return "Neo Pro — 40 фото ⭐ самый популярный\nАватарки, дейтинг, соцсети"
    if pack.id == "neo_unlimited":
        return "Neo Unlimited — 120 фото\nДля частого использования"
    return f"{pack.name} — {pack.description or ''}"


def get_balance_line(db, telegram_id: str) -> str:
    """
    Одна строка баланса: «Осталось фото: N» или «Купите пакет, чтобы начать».
    В пользовательском UI отдельный счётчик 4K не показываем (терминология NeoBanana).
    """
    user_svc = UserService(db)
    session_svc = SessionService(db)
    user = user_svc.get_by_telegram_id(telegram_id)
    if not user:
        return "Купите пакет, чтобы начать."
    session = session_svc.get_active_session(user.id)
    if not session:
        return "Купите пакет, чтобы начать."
    remaining = session.takes_limit - session.takes_used
    return f"Осталось фото: {remaining} из {session.takes_limit}"


def _shop_body_text(packs: list) -> str:
    """Текст блока выбора пакета: заголовок, пояснения, список пакетов без цен."""
    lines = [
        "Выберите пакет 👇",
        "",
        "Превью из 3 фото бесплатно.",
        "4K без водяного знака — после оплаты.",
        "",
    ]
    for pack in packs:
        lines.append(_pack_text_line(pack))
    return "\n".join(lines)


def build_balance_tariffs_message(db, telegram_id: str, star_to_rub: float = 1.3) -> tuple[str, dict | None]:
    """
    Собрать текст и reply_markup для экрана магазина (выбор пакета).
    Порядок: Neo Start → Neo Pro → Neo Unlimited → Пробный. Пробный только если trial_purchased=False.
    """
    user_svc = UserService(db)
    payment_service = PaymentService(db)
    session_svc = SessionService(db)

    user = user_svc.get_by_telegram_id(telegram_id)
    session = session_svc.get_active_session(user.id) if user else None
    has_session = bool(session)
    show_trial = user and not getattr(user, "trial_purchased", True)

    packs = payment_service.list_product_ladder_packs()
    by_id = {}
    for p in packs:
        if getattr(p, "pack_subtype", "standalone") == "collection" and not getattr(p, "playlist", None):
            continue
        by_id[p.id] = p

    ordered = []
    for pid in DISPLAY_ORDER:
        if pid == "trial" and not show_trial:
            continue
        if pid in by_id:
            ordered.append(by_id[pid])

    if not ordered:
        body = _shop_body_text([]) + "\n\n(Пакеты временно недоступны.)"
        return body, None

    body = _shop_body_text(ordered)
    if has_session:
        balance_line = get_balance_line(db, telegram_id)
        text = f"{balance_line}\n\n{body}"
    else:
        text = body
    buttons = []

    for pack in ordered:
        rub = DISPLAY_RUB.get(pack.id) or round(pack.stars_price * star_to_rub)
        if pack.id == "trial":
            label = f"{pack.emoji} Попробовать 1 фото · {rub} ₽"
        elif pack.id == "neo_start":
            label = f"{pack.emoji} Neo Start · 10 фото · {rub} ₽"
        elif pack.id == "neo_pro":
            label = f"{pack.emoji} Neo Pro · 40 фото · {rub} ₽ ⭐"
        elif pack.id == "neo_unlimited":
            label = f"{pack.emoji} Neo Unlimited · 120 фото · {rub} ₽"
        else:
            label = f"{pack.emoji} {pack.name} · {rub} ₽"
        buttons.append([{"text": label, "callback_data": f"paywall:{pack.id}"}])
    buttons.append([{"text": "📘 Как пополнить", "callback_data": "profile:payment"}])
    buttons.append([{"text": "📋 В меню", "callback_data": "nav:menu"}])
    return text, {"inline_keyboard": buttons}
