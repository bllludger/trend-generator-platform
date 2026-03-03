"""
Подготовка изображений для отправки в Telegram.
Telegram принимает фото до 10 MB — при большем размере создаём сжатую копию.
"""
from __future__ import annotations

import logging
import os
import tempfile

from PIL import Image

logger = logging.getLogger(__name__)

# Лимит Telegram для sendPhoto (байты)
TELEGRAM_MAX_PHOTO_BYTES = 10 * 1024 * 1024  # 10 MB
# Целевой размер при сжатии (оставляем запас)
TARGET_MAX_BYTES = 9 * 1024 * 1024  # 9 MB
MAX_SIDE_PX = 1920
JPEG_QUALITY = 85


def path_for_telegram_photo(image_path: str) -> tuple[str, bool]:
    """
    Возвращает путь к файлу, подходящий для sendPhoto (до 10 MB).
    Если исходный файл больше лимита — создаёт сжатую копию во временном файле.

    Returns:
        (path, is_temp): path — путь к файлу для отправки; is_temp — True если создан
        временный файл (нужно удалить после отправки).
    """
    if not image_path or not os.path.isfile(image_path):
        return image_path, False
    size = os.path.getsize(image_path)
    if size <= TELEGRAM_MAX_PHOTO_BYTES:
        return image_path, False

    try:
        with Image.open(image_path) as img:
            # JPEG поддерживает только RGB; остальные режимы конвертируем
            img = img.convert("RGB") if img.mode != "RGB" else img
            w, h = img.size
            if max(w, h) > MAX_SIDE_PX:
                ratio = MAX_SIDE_PX / max(w, h)
                new_size = (int(w * ratio), int(h * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
            fd, path = tempfile.mkstemp(suffix=".jpg")
            os.close(fd)
            img.save(path, "JPEG", quality=JPEG_QUALITY, optimize=True)
            out_size = os.path.getsize(path)
            if out_size > TELEGRAM_MAX_PHOTO_BYTES:
                # ещё уменьшаем качество
                for q in (75, 65, 55):
                    img.save(path, "JPEG", quality=q, optimize=True)
                    if os.path.getsize(path) <= TELEGRAM_MAX_PHOTO_BYTES:
                        break
            logger.info(
                "telegram_photo_compressed",
                extra={"original": image_path, "original_bytes": size, "compressed_bytes": os.path.getsize(path)},
            )
            return path, True
    except Exception as e:
        logger.warning("telegram_photo_compress_failed", extra={"path": image_path, "error": str(e)})
        return image_path, False
