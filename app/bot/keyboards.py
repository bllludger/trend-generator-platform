"""Keyboard builders extracted from main.py."""
from typing import Any

from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)

from app.bot.helpers import t, get_db_session
from app.bot.constants import (
    TREND_CUSTOM_ID,
    THEME_CB_PREFIX,
    NAV_THEMES,
    SUBSCRIPTION_CHANNEL_USERNAME,
    SUBSCRIPTION_CALLBACK,
    GENERATION_NEGATIVE_REASONS,
)
from app.services.generation_prompt.settings_service import GenerationPromptSettingsService


def _compact_trend_label(emoji: str, name: str, max_len: int = 18) -> str:
    """Короткий и аккуратный лейбл тренда для Telegram-кнопок."""
    clean_name = (name or "").strip()
    if len(clean_name) > max_len:
        clean_name = clean_name[: max_len - 1].rstrip() + "…"
    base = f"{(emoji or '').strip()} {clean_name}".strip()
    return base or "Тренд"


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=t("menu.btn.create_photo", "🔥 Создать фото")),
                KeyboardButton(text=t("menu.btn.copy_style", "🔄 Сделать такую же")),
            ],
            [
                KeyboardButton(text=t("menu.btn.merge_photos", "🧩 Соединить фото")),
                KeyboardButton(text=t("menu.btn.shop", "🛒 Купить пакет")),
            ],
            [
                KeyboardButton(text=t("menu.btn.profile", "👤 Мой профиль")),
            ],
        ],
        resize_keyboard=True,
    )


def create_photo_only_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура только с кнопкой «Создать фото» — шаг сразу после подписки на канал."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t("menu.btn.create_photo", "🔥 Создать фото"))],
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
    """Клавиатура трендов одной тематики (страница N). Адаптивная сетка 2xN для лучшей читаемости."""
    buttons: list[list[InlineKeyboardButton]] = []
    # 2 колонки: кнопки заметно шире и легче читаются на телефонах.
    for i in range(0, len(trends_page), 2):
        row = [
            InlineKeyboardButton(
                text=_compact_trend_label(t.get("emoji", ""), t.get("name", "")),
                callback_data=f"trend:{t['id']}",
            )
            for t in trends_page[i : i + 2]
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
        [InlineKeyboardButton(text=_compact_trend_label(t.get("emoji", ""), t.get("name", "")), callback_data=f"trend:{t['id']}")]
        for t in trends
    ]
    buttons.append([InlineKeyboardButton(text=t("menu.btn.custom_idea", "💡 Своя идея"), callback_data=f"trend:{TREND_CUSTOM_ID}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _get_default_aspect_ratio() -> str:
    """Дефолтное соотношение сторон из админки (Мастер промпт → На релиз → default_aspect_ratio)."""
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
    """Клавиатура выбора соотношения сторон. Дефолт из админки помечается « (по умолч.)»; выбор пользователя приоритетный."""
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


def _feedback_keyboard(take_id: str, variant: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👍 Нравится", callback_data=f"gen_fb:{take_id}:{variant}:1"),
            InlineKeyboardButton(text="👎 Не нравится", callback_data=f"gen_fb:{take_id}:{variant}:0"),
        ],
        [
            InlineKeyboardButton(text="✅ Похоже на меня", callback_data=f"ln:{take_id}:{variant}:yes"),
            InlineKeyboardButton(text="❌ Не похоже", callback_data=f"ln:{take_id}:{variant}:no"),
        ],
    ])


def _negative_reason_keyboard(take_id: str, variant: str) -> InlineKeyboardMarkup:
    row1 = [InlineKeyboardButton(text=label, callback_data=f"nr:{take_id}:{variant}:{slug}") for slug, label in GENERATION_NEGATIVE_REASONS[:4]]
    row2 = [InlineKeyboardButton(text=label, callback_data=f"nr:{take_id}:{variant}:{slug}") for slug, label in GENERATION_NEGATIVE_REASONS[4:]]
    return InlineKeyboardMarkup(inline_keyboard=[row1, row2])


def _subscription_keyboard():
    """Клавиатура: ссылка на канал + «Я подписался»."""
    if not SUBSCRIPTION_CHANNEL_USERNAME:
        return None
    channel_url = f"https://t.me/{SUBSCRIPTION_CHANNEL_USERNAME}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t("subscription.btn.channel", "📢 Перейти в канал"), url=channel_url)],
        [InlineKeyboardButton(text=t("subscription.btn.done", "✅ Я подписался"), callback_data=SUBSCRIPTION_CALLBACK)],
    ])


def _profile_keyboard(*, is_paid_active: bool, has_remaining: bool, is_trial_profile: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура профиля: для paid — быстрые рабочие действия без навязчивого upsell."""
    buttons = []
    if is_paid_active:
        buttons.append([InlineKeyboardButton(text="🤝 Пригласить друга — бонусы", callback_data="referral:invite")])
        buttons.append([InlineKeyboardButton(text="🆘 Поддержка", callback_data="profile:support")])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    if is_trial_profile:
        buttons.extend(
            [
                [InlineKeyboardButton(text="🔗 Получить свою ссылку", callback_data="trial_ref:get_link")],
                [InlineKeyboardButton(text=t("menu.btn.shop", "🛒 Купить пакет"), callback_data="shop:open")],
                [InlineKeyboardButton(text="🆘 Поддержка", callback_data="profile:support")],
            ]
        )
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    buttons.extend(
        [
            [InlineKeyboardButton(text=t("menu.btn.shop", "🛒 Купить пакет"), callback_data="shop:open")],
            [InlineKeyboardButton(text="🔗 Получить свою ссылку", callback_data="trial_ref:get_link")],
            [InlineKeyboardButton(text="🤝 Пригласить друга — бонусы", callback_data="referral:invite")],
            [InlineKeyboardButton(text="💵 Оплата через ЮMoney", callback_data="profile:payment")],
            [InlineKeyboardButton(text="🆘 Поддержка", callback_data="profile:support")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def audience_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора ЦА: Я — женщина, Я — мужчина, Мы — пара."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t("audience.women", "👩 Я — женщина"), callback_data="audience:women"),
            InlineKeyboardButton(text=t("audience.men", "👨 Я — мужчина"), callback_data="audience:men"),
        ],
        [InlineKeyboardButton(text=t("audience.couples", "👩‍❤️‍👨 Мы — пара"), callback_data="audience:couples")],
    ])


def _payment_method_keyboard(pack_id: str):
    """Клавиатура выбора способа оплаты: только ЮMoney."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💵 Оплатить через ЮMoney", callback_data=f"pay_method:yoomoney:{pack_id}")],
        [InlineKeyboardButton(text="🔗 Оплатить по ссылке (ЮMoney)", callback_data=f"pay_method:yoomoney_link:{pack_id}")],
        [InlineKeyboardButton(text="🛟 Помощь", callback_data="profile:support")],
        [InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")],
    ])
