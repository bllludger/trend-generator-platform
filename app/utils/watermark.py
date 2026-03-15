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


def _draw_tiled_text_layer(
    size: tuple[int, int],
    diag: float,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    tile_spacing: int,
    fill_rgba: tuple[int, int, int, int],
    offset_xy: tuple[int, int] = (0, 0),
) -> Image.Image:
    """Рисует тайловый текст на увеличенном слое, поворачивает и обрезает до size."""
    width, height = size
    max_dim = int(diag * 1.5)
    txt_layer = Image.new("RGBA", (max_dim, max_dim), (0, 0, 0, 0))
    txt_draw = ImageDraw.Draw(txt_layer)
    bbox = txt_draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    ox, oy = offset_xy
    y = 0
    while y < max_dim:
        x = 0
        while x < max_dim:
            txt_draw.text((x + ox, y + oy), text, font=font, fill=fill_rgba)
            x += text_width + tile_spacing
        y += text_height + tile_spacing
    txt_layer = txt_layer.rotate(30, resample=Image.BICUBIC, expand=False)
    cx, cy = txt_layer.width // 2, txt_layer.height // 2
    crop_box = (
        cx - width // 2,
        cy - height // 2,
        cx - width // 2 + width,
        cy - height // 2 + height,
    )
    return txt_layer.crop(crop_box)


def apply_watermark(
    image_path: str,
    output_path: str,
    text: str = "@ai_nanobananastudio_bot",
    opacity: int = 60,
    tile_spacing: int = 200,
) -> str:
    """
    Накладывает полупрозрачный текст по диагонали (тайлинг) на изображение.
    Legacy: сохраняет в output_path по расширению. Для нового кода используйте apply_watermark_v2.
    """
    result_rgb = apply_watermark_v2(
        image_path, text=text, opacity=opacity, tile_spacing=tile_spacing, use_contrast=False
    )
    ext = os.path.splitext(output_path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        result_rgb.save(output_path, "JPEG", quality=95)
    elif ext == ".webp":
        result_rgb.save(output_path, "WEBP", quality=95)
    else:
        result_rgb.save(output_path, "PNG")
    logger.info("watermark_applied", extra={"input": image_path, "output": output_path, "text": text})
    return output_path


def apply_watermark_v2(
    image_path: str,
    text: str = "@ai_nanobananastudio_bot",
    opacity: int = 60,
    tile_spacing: int = 200,
    use_contrast: bool = True,
) -> Image.Image:
    """
    Накладывает вотермарк на изображение и возвращает RGB PIL Image (не сохраняет файл).
    При use_contrast=True: двухслойный контрастный вотермарк (тёмный слой + светлый),
    читаемый на светлом, тёмном и смешанном фоне.
    """
    try:
        img = Image.open(image_path).convert("RGBA")
        width, height = img.size
        diag = math.sqrt(width**2 + height**2)
        font_size = max(20, int(diag * 0.03))
        font = _get_font(font_size)

        if use_contrast:
            # Тёмный слой (тень/контур): смещение 2px для «обводки»
            dark_opacity = min(255, opacity + 40)
            dark_layer = _draw_tiled_text_layer(
                (width, height), diag, text, font, tile_spacing,
                fill_rgba=(0, 0, 0, dark_opacity),
                offset_xy=(2, 2),
            )
            img = Image.alpha_composite(img, dark_layer)
            # Светлый слой поверх
            light_layer = _draw_tiled_text_layer(
                (width, height), diag, text, font, tile_spacing,
                fill_rgba=(255, 255, 255, opacity),
                offset_xy=(0, 0),
            )
            result = Image.alpha_composite(img, light_layer)
        else:
            layer = _draw_tiled_text_layer(
                (width, height), diag, text, font, tile_spacing,
                fill_rgba=(255, 255, 255, opacity),
            )
            result = Image.alpha_composite(img, layer)

        result_rgb = result.convert("RGB")
        logger.info(
            "watermark_applied",
            extra={"input": image_path, "text": text, "use_contrast": use_contrast},
        )
        return result_rgb
    except Exception:
        logger.exception("watermark_failed", extra={"input": image_path})
        raise
