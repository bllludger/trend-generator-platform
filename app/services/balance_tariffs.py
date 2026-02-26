"""
Шаблон «Баланс + Выбор фотосессии» (outcome-first).
Один экран выбора фотосессии: без «пополнить баланс»/«генерации»/токенов.
Порядок: Avatar → Dating → Creator → Trial (Trial последний и только если trial_purchased=false).
"""
from __future__ import annotations

from app.models.pack import Pack
from app.services.payments.service import PaymentService, PRODUCT_LADDER_IDS
from app.services.sessions.service import SessionService
from app.services.users.service import UserService

# Порядок кнопок и списка: Avatar → Dating → Creator → Trial (Trial внизу)
DISPLAY_ORDER = ("avatar_pack", "dating_pack", "creator", "trial")

# Короткие имена для экрана (без «Pack» и т.п.)
SHORT_NAMES = {
    "trial": "Trial",
    "avatar_pack": "Avatar",
    "dating_pack": "Dating",
    "creator": "Creator",
}


def _pack_outcome_label(pack: Pack) -> str:
    """Короткие outcome-подписи без техпараметров (HD, takes_limit)."""
    if pack.id == "trial":
        return "1 снимок для пробы"
    if pack.id == "avatar_pack":
        return "4 стиля аватара"
    if pack.id == "dating_pack":
        return "6 образов для дейтинга"
    if pack.id == "creator":
        return "Студия MAX"
    return pack.description or ""


def get_balance_line(db, telegram_id: str) -> str:
    """
    Блок заголовка: остаток снимков/HD или «Нет активной фотосессии».
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
    return f"Осталось снимков: {remaining} из {session.takes_limit}\nHD доступно: {hd_rem}"


def _subheader(has_session: bool) -> str:
    if has_session:
        return "Хочешь больше образов? Выбери фотосессию:"
    return "Выбери фотосессию:"


def build_balance_tariffs_message(db, telegram_id: str, star_to_rub: float = 1.3) -> tuple[str, dict | None]:
    """
    Собрать текст и reply_markup для экрана «Выбор фотосессии».
    Порядок: Avatar → Dating → Creator → Trial. Trial только если trial_purchased=False.
    Без рублёвого эквивалента и техпараметров в списке тарифов.
    """
    user_svc = UserService(db)
    payment_service = PaymentService(db)
    session_svc = SessionService(db)

    user = user_svc.get_by_telegram_id(telegram_id)
    has_session = bool(user and session_svc.get_active_session(user.id) if user else False)
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
        sub = _subheader(has_session)
        return f"{balance_line}\n\n{sub}\n\n(Тарифы временно недоступны.)", None

    balance_line = get_balance_line(db, telegram_id)
    sub = _subheader(has_session)
    text = f"{balance_line}\n\n{sub}\n\n"
    buttons = []

    for pack in ordered:
        short = SHORT_NAMES.get(pack.id, pack.name)
        text += f"{pack.emoji} {short} — {pack.stars_price}⭐\n"
        badge = " • Лучший выбор" if pack.id == "dating_pack" else (" • Max" if pack.id == "creator" else "")
        label = f"{pack.emoji} {short}{badge} — {pack.stars_price}⭐"
        buttons.append([{"text": label, "callback_data": f"paywall:{pack.id}"}])

    text += "\n👇 Выбирай подходящий пакет"
    buttons.append([{"text": "💳 Не знаю как купить Stars", "callback_data": "bank_transfer:start"}])
    buttons.append([{"text": "📋 В меню", "callback_data": "nav:menu"}])
    return text, {"inline_keyboard": buttons}
