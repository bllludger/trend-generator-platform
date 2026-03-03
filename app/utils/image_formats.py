"""
Общий маппинг aspect ratio → size (px) для бота и воркеров.
Выбор пользователя приоритетный; при отсутствии используется default_aspect_ratio из админки.
"""

# Соответствие формата кадра (как в кнопках бота) размеру для провайдеров генерации
ASPECT_RATIO_TO_SIZE: dict[str, str] = {
    "1:1": "1024x1024",   # Квадрат
    "16:9": "1024x576",   # Широкий
    "4:3": "1024x768",    # Классика
    "9:16": "576x1024",   # Портрет
    "3:4": "768x1024",     # Вертикальный
}

DEFAULT_ASPECT_RATIO = "1:1"
DEFAULT_SIZE = "1024x1024"


def aspect_ratio_to_size(aspect_ratio: str | None) -> str:
    """Вернуть size (например 1024x1024) по aspect_ratio из админки или выбора пользователя."""
    if not aspect_ratio or not (aspect_ratio or "").strip():
        return DEFAULT_SIZE
    ar = (aspect_ratio or "").strip()
    return ASPECT_RATIO_TO_SIZE.get(ar, DEFAULT_SIZE)
