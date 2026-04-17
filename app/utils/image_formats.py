"""
Общий маппинг aspect ratio → size (px) для бота и воркеров.
Выбор пользователя приоритетный; при отсутствии используется default_aspect_ratio из админки.
"""

# Соответствие формата кадра (как в кнопках бота) размеру для провайдеров генерации
ASPECT_RATIO_TO_SIZE: dict[str, str] = {
    "1:1": "1024x1024",
    "3:2": "1024x683",
    "2:3": "683x1024",
    "3:4": "768x1024",
    "4:3": "1024x768",
    "4:5": "819x1024",
    "5:4": "1024x819",
    "9:16": "576x1024",
    "16:9": "1024x576",
    "21:9": "1024x439",
    "1:4": "256x1024",
    "4:1": "1024x256",
    "1:8": "128x1024",
    "8:1": "1024x128",
}

DEFAULT_ASPECT_RATIO = "3:4"
DEFAULT_SIZE = "768x1024"


def aspect_ratio_to_size(aspect_ratio: str | None) -> str:
    """Вернуть size (например 1024x1024) по aspect_ratio из админки или выбора пользователя."""
    if not aspect_ratio or not (aspect_ratio or "").strip():
        return DEFAULT_SIZE
    ar = (aspect_ratio or "").strip()
    return ASPECT_RATIO_TO_SIZE.get(ar, DEFAULT_SIZE)
