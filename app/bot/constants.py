"""Bot-level constants extracted from main.py."""

import logging
import os

from app.core.config import settings
from app.utils.image_formats import ASPECT_RATIO_TO_SIZE

logger = logging.getLogger("bot")

# ---------------------------------------------------------------------------
# Image paths
# ---------------------------------------------------------------------------
_BOT_ROOT = os.path.dirname(os.path.abspath(__file__))
_PROJECT_IMAGE_DIR = os.path.join(_BOT_ROOT, "..", "..", "image")
WELCOME_IMAGE_PATH = os.path.join(_PROJECT_IMAGE_DIR, "start_2.png")
MONEY_IMAGE_PATH = os.path.join(_PROJECT_IMAGE_DIR, "money_4.png")
RULE_IMAGE_PATH = os.path.join(_PROJECT_IMAGE_DIR, "rule_2.png")
COPY_STYLE_INTRO_IMAGE_PATH = os.path.join(_PROJECT_IMAGE_DIR, "Без названия (16).png")
MERGE_INTRO_IMAGE_PATH = os.path.join(_PROJECT_IMAGE_DIR, "merge_2.png")
PAYMENT_SUCCESS_IMAGE_PATH = os.path.join(_PROJECT_IMAGE_DIR, "payments_yes.png")
SUBSCRIPTION_IMAGE_PATH = os.path.join(_PROJECT_IMAGE_DIR, "подпс_на_канал_2.png")
SUCCESS_IMAGE_PATH = os.path.join(_PROJECT_IMAGE_DIR, "успех_33.png")
GENERATION_INTRO_IMAGE_PATH = os.path.join(_PROJECT_IMAGE_DIR, "оплата2.png")
GENERATION_INTRO_IMAGE_PATH_WOMEN = os.path.join(_PROJECT_IMAGE_DIR, "3var_girl.png")
GENERATION_INTRO_IMAGE_PATH_MEN = os.path.join(_PROJECT_IMAGE_DIR, "3var_man.png")
GENERATION_INTRO_IMAGE_PATH_COUPLES = os.path.join(_PROJECT_IMAGE_DIR, "3var_para.png")

# ---------------------------------------------------------------------------
# Default texts
# ---------------------------------------------------------------------------
WELCOME_TEXT_DEFAULT = (
    "👋 NeoBanana — ИИ фотостудия\n\n"
    "Фото, которые выглядят как профессиональная съёмка —\n"
    "в любом образе, сразу готовые для соцсетей\n\n"
    "Загрузите своё лучшее фото, выберите стиль\n"
    "и получите результат как после профессиональной съёмки — за пару минут\n\n"
    "👇 Попробовать бесплатно\n\n"
    "🍌"
)

HELP_TEXT_DEFAULT = (
    "🎨 *NeoBanana — ИИ фотостудия*\n\n"
    "*Как использовать:*\n"
    "1. «🔥 Создать фото» — отправьте фото, выберите тренд, формат — результат!\n"
    "2. «🔄 Сделать такую же» — загрузите образец, затем своё фото — копия стиля 1:1\n"
    "3. «🛒 Купить пакет» — пакеты фото без водяного знака\n"
    "4. «👤 Мой профиль» — баланс и статистика\n\n"
    "*Как работает оплата:*\n"
    "— 3 бесплатных превью (с водяным знаком)\n"
    "— Купите пакет — оплата через ЮMoney (карта/кошелёк)\n"
    "— Можно разблокировать отдельное фото\n\n"
    "*Команды:*\n"
    "/start — Начать\n"
    "/help — Помощь\n"
    "/cancel — Отменить выбор\n"
    "/terms — Условия использования\n"
    "/paysupport — Поддержка по платежам\n"
    "Поддержка: @{support_username}\n\n"
    "*Форматы фото:* JPG, PNG, WEBP\n"
    "*Максимальный размер:* {max_file_size_mb} МБ"
)

GENERATION_INTRO_TEXT = (
    "Готовим для тебя 3 готовых образа\n\n"
    "Скоро увидишь варианты и выберешь тот, который тебе подходит"
)

REFERENCE_NOTE_DEFAULT = "📎 Фото пользователя закреплены как Image B (REFERENCE) и будут участвовать в генерации."

PHOTO_ACCEPTED_CAPTION_DEFAULT = (
    "Фото принято ✅\n\n"
    "Отлично! Мы получили ваше фото\n"
    "и готовы создать для вас фотосессию\n"
    "в любом выбранном образе.\n\n"
    "Теперь выберите стиль 👇"
)

THEME_SELECTED_INSTRUCTION = (
    "🔥 Остался последний шаг!\n\n"
    "Выберите образ для своей фотографии.\n\n"
    "✨ В каждом тренде — примеры\n"
    "готовых фотосессий и образов.\n\n"
    "👇 Нажмите на любой тренд\n"
    "посмотрите фото и выберите стиль.\n\n"
    "🔄 Если не понравилось —\n"
    "вернитесь назад и попробуйте другой."
)

REQUEST_PHOTO_TEXT_DEFAULT = (
    "📸 Загрузите своё лучшее фото\n\n"
    "✨ Бесплатное превью для любого тренда\n\n"
    "❗ Важно для качественного результата:\n"
    "• светлое селфи напротив окна\n"
    "• отправляйте фото файлом (без сжатия)\n"
    "• без домашнего образа\n\n"
    "👇 Просто отправьте своё фото в чат"
)

AUDIENCE_PROMPT_DEFAULT = "Для кого фотосессия?"

AUDIENCE_MEN_OFFRAMP_TEXT = (
    "Извините, мы пока не работаем с мужскими профилями. "
    "Скоро добавим тренды для мужчин.\n\n"
    "Подпишитесь на канал, чтобы первыми узнать о запуске."
)

# ---------------------------------------------------------------------------
# Config constants
# ---------------------------------------------------------------------------
IMAGE_FORMATS = ASPECT_RATIO_TO_SIZE
DEFAULT_ASPECT_RATIO = "3:4"
TREND_CUSTOM_ID = "custom"
# 8 карточек на страницу (2 колонки x 4 ряда): шире кнопки и больше трендов за экран.
TRENDS_PER_PAGE = 8
THEME_CB_PREFIX = "theme:"
NAV_THEMES = "nav:themes"

# ---------------------------------------------------------------------------
# Subscription constants
# ---------------------------------------------------------------------------
SUBSCRIPTION_CHANNEL_USERNAME = (getattr(settings, "subscription_channel_username", None) or "").strip()
SUBSCRIPTION_CALLBACK = "subscription_check"

SUBSCRIBE_TEXT_DEFAULT = (
    "Чтобы начать создание фото, подпишитесь на канал NeoBanana.\n\n"
    "Что будет в канале:\n"
    "✨ примеры готовых образов\n"
    "🔥 новые тренды и идеи для фото\n"
    "📌 обновления сервиса\n\n"
    "Как начать:\n"
    "1. Нажмите «📢 Перейти в канал»\n"
    "2. Подпишитесь\n"
    "3. Вернитесь в бот и нажмите «✅ Я подписался»\n\n"
    "После этого создание фото станет доступно."
)

AFTER_SUBSCRIPTION_TEXT = (
    "Готово, вы подписались ✅\n\n"
    "Давайте сделаем первый результат 👇\n\n"
    "Загрузите своё лучшее селфи\n"
    "и получите фото в любом образе — как после профессиональной съёмки, готовое для соцсетей\n\n"
    "Вам доступно бесплатно:\n"
    "• 3 образа из трендов\n\n"
    "🔥 Создать фото"
)

# ---------------------------------------------------------------------------
# Negative reasons (product analytics feedback)
# ---------------------------------------------------------------------------
GENERATION_NEGATIVE_REASONS = [
    ("face_not_similar", "Лицо не похоже"),
    ("strange_details", "Странные детали"),
    ("wrong_style", "Не тот стиль"),
    ("bad_background", "Плохой фон"),
    ("pose_problem", "Поза/композиция"),
    ("low_quality", "Низкое качество"),
    ("other", "Другое"),
]
