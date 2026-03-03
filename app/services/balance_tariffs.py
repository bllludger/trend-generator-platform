"""
Шаблон «Баланс + Выбор фотосессии» (outcome-first).
Один экран выбора фотосессии: без «пополнить баланс»/«генерации»/токенов.
Порядок: Neo Start → Neo Pro → Neo Unlimited → Trial (Trial последний и только если trial_purchased=false).
"""
from __future__ import annotations

from app.models.pack import Pack
from app.services.payments.service import PaymentService, PRODUCT_LADDER_IDS
from app.services.sessions.service import SessionService
from app.services.users.service import UserService
from app.utils.currency import format_stars_rub

DISPLAY_ORDER = ("neo_start", "neo_pro", "neo_unlimited", "trial")

SHORT_NAMES = {
    "trial": "Trial",
    "neo_start": "Neo Start",
    "neo_pro": "Neo Pro ⭐ Хит",
    "neo_unlimited": "Neo Unlimited",
}


def _pack_outcome_label(pack: Pack) -> str:
    """Короткие outcome-подписи."""
    if pack.id == "trial":
        return "1 снимок для пробы"
    if pack.id == "neo_start":
        return "10 образов"
    if pack.id == "neo_pro":
        return "40 образов"
    if pack.id == "neo_unlimited":
        return "120 образов"
    return pack.description or ""


def get_balance_line(db, telegram_id: str) -> str:
    """
    Блок заголовка: остаток снимков/4K или «Нет активной фотосессии».
    Возвращает 1–2 строки баланса (без подзаголовка «Выбери фотосессию»).
    """
    user_svc = UserService(db)
    session_svc = SessionService(db)
    user = user_svc.get_by_telegram_id(telegram_id)
    if not user:
        return "Нет активной фотосессии."
    session = session_svc.get_active_session(user.id)
    if not session:
        return "Нет активной фотосессии."
    remaining = session.takes_limit - session.takes_used
    hd_rem = session_svc.hd_remaining(session)
    return f"Осталось снимков: {remaining} из {session.takes_limit}\n4K без watermark: {hd_rem}"


def _subheader(has_session: bool, remaining: int | None = None, pack_id: str | None = None) -> str:
    """Подзаголовок перед списком пакетов. «Хочешь больше образов?» — только когда закончился платный пакет, не Trial."""
    if not has_session:
        return "Выбери фотосессию:"
    if remaining == 0 and pack_id == "trial":
        return "Триал завершён. Выбери пакет для продолжения:"
    if has_session:
        return "Хочешь больше образов? Выбери фотосессию:"
    return "Выбери фотосессию:"


def build_balance_tariffs_message(db, telegram_id: str, star_to_rub: float = 1.3) -> tuple[str, dict | None]:
    """
    Собрать текст и reply_markup для экрана «Выбор фотосессии».
    Порядок: Neo Start → Neo Pro → Neo Unlimited → Trial. Trial только если trial_purchased=False.
    """
    user_svc = UserService(db)
    payment_service = PaymentService(db)
    session_svc = SessionService(db)

    user = user_svc.get_by_telegram_id(telegram_id)
    session = session_svc.get_active_session(user.id) if user else None
    has_session = bool(session)
    remaining = (session.takes_limit - session.takes_used) if session else None
    pack_id = session.pack_id if session else None
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
        balance_line = get_balance_line(db, telegram_id)
        sub = _subheader(has_session, remaining, pack_id)
        return f"{balance_line}\n\n{sub}\n\n(Тарифы временно недоступны.)", None

    balance_line = get_balance_line(db, telegram_id)
    sub = _subheader(has_session, remaining, pack_id)
    text = f"{balance_line}\n\n{sub}\n\n"
    buttons = []

    for pack in ordered:
        short = SHORT_NAMES.get(pack.id, pack.name)
        outcome = _pack_outcome_label(pack)
        price_str = format_stars_rub(pack.stars_price, star_to_rub)
        # Количество и цена наглядно (жирным в HTML)
        text += f"{pack.emoji} {short}: <b>{outcome}</b> — <b>{price_str}</b>\n"
        badge = " • Хит" if pack.id == "neo_pro" else ""
        label = f"{pack.emoji} {short}{badge} · {outcome} · {price_str}"
        buttons.append([{"text": label, "callback_data": f"paywall:{pack.id}"}])

    text += "\n👇 Выбирай подходящий пакет"
    buttons.append([{"text": "💳 Не знаю как купить Stars", "callback_data": "bank_transfer:start"}])
    buttons.append([{"text": "📋 В меню", "callback_data": "nav:menu"}])
    return text, {"inline_keyboard": buttons}
