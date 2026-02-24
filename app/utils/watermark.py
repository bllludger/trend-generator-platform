"""
Watermark utility — наложение полупрозрачного текста по диагонали.
Используется для превью бесплатных генераций.
"""
import math
import os
import logging

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Путь к встроенному шрифту Pillow (fallback)
_FONT_FALLBACK = None


def _get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Попытка загрузить TrueType шрифт нужного размера."""
    # Попробуем системные шрифты
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    # Fallback — Pillow default
    try:
        return ImageFont.truetype("DejaVuSans-Bold", size)
    except Exception:
        return ImageFont.load_default()


def apply_watermark(
    image_path: str,
    output_path: str,
    text: str = "NanoBanan Preview",
    opacity: int = 60,
    tile_spacing: int = 200,
) -> str:
    """
    Накладывает полупрозрачный текст по диагонали (тайлинг) на изображение.

    Args:
        image_path: путь к исходному изображению
        output_path: путь для сохранения результата
        text: текст watermark
        opacity: прозрачность (0-255, 60 = ~24%)
        tile_spacing: расстояние между повторениями текста

    Returns:
        output_path — путь к изображению с watermark
    """
    try:
        img = Image.open(image_path).convert("RGBA")
        width, height = img.size

        # Создаём прозрачный слой для watermark
        watermark_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(watermark_layer)

        # Размер шрифта пропорционально изображению (примерно 3% от диагонали)
        diag = math.sqrt(width ** 2 + height ** 2)
        font_size = max(20, int(diag * 0.03))
        font = _get_font(font_size)

        # Получаем размер текста
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        # Создаём увеличенный слой для поворота (чтобы текст покрыл всё изображение)
        max_dim = int(diag * 1.5)
        txt_layer = Image.new("RGBA", (max_dim, max_dim), (0, 0, 0, 0))
        txt_draw = ImageDraw.Draw(txt_layer)

        # Тайлим текст по всему увеличенному слою
        y = 0
        while y < max_dim:
            x = 0
            while x < max_dim:
                txt_draw.text(
                    (x, y),
                    text,
                    font=font,
                    fill=(255, 255, 255, opacity),
                )
                x += text_width + tile_spacing
            y += text_height + tile_spacing

        # Поворачиваем на -30 градусов
        txt_layer = txt_layer.rotate(30, resample=Image.BICUBIC, expand=False)

        # Обрезаем до размера исходного изображения (центр)
        cx = txt_layer.width // 2
        cy = txt_layer.height // 2
        crop_box = (
            cx - width // 2,
            cy - height // 2,
            cx - width // 2 + width,
            cy - height // 2 + height,
        )
        txt_cropped = txt_layer.crop(crop_box)

        # Накладываем watermark
        result = Image.alpha_composite(img, txt_cropped)

        # Сохраняем в RGB (для PNG/JPG совместимости)
        result_rgb = result.convert("RGB")

        # Определяем формат по расширению
        ext = os.path.splitext(output_path)[1].lower()
        if ext in (".jpg", ".jpeg"):
            result_rgb.save(output_path, "JPEG", quality=95)
        elif ext == ".webp":
            result_rgb.save(output_path, "WEBP", quality=95)
        else:
            result_rgb.save(output_path, "PNG")

        logger.info(
            "watermark_applied",
            extra={"input": image_path, "output": output_path, "text": text},
        )
        return output_path
    except Exception:
        logger.exception("watermark_failed", extra={"input": image_path})
        raise
