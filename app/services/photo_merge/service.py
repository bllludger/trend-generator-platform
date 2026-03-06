"""
PhotoMergeService: склеивает 2-3 изображения в одно с авто-макетом.

Макеты:
  2 фото — горизонтально в ряд (side-by-side).
  3 фото — сетка 2+1: две сверху, одна снизу по центру.

Все входные фото выравниваются по высоте строки (downscale only, качество Lanczos).
Цветовой профиль унифицируется в RGB перед склейкой.
EXIF Orientation корректируется автоматически.
"""
from __future__ import annotations

import io
import logging
import os

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)


def _open_corrected(path: str) -> Image.Image:
    """Открыть изображение с коррекцией EXIF Orientation и конвертацией в RGB."""
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    return img


def _resize_to_height(img: Image.Image, target_h: int) -> Image.Image:
    """Уменьшить изображение до нужной высоты (только downscale)."""
    w, h = img.size
    if h <= target_h:
        return img
    ratio = target_h / h
    return img.resize((int(w * ratio), target_h), Image.Resampling.LANCZOS)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return r, g, b


class PhotoMergeService:
    """Основная логика склейки, не зависящая от БД/Celery."""

    def merge(
        self,
        input_paths: list[str],
        output_path: str,
        output_format: str = "png",
        jpeg_quality: int = 92,
        max_output_side_px: int = 0,
        background_color: str = "#ffffff",
    ) -> dict:
        """
        Склеить фото по пути, сохранить результат в output_path.
        Returns dict с метриками: input_bytes, output_bytes.
        """
        n = len(input_paths)
        if n < 2 or n > 3:
            raise ValueError(f"PhotoMergeService: ожидается 2 или 3 фото, получено {n}")

        input_bytes = sum(os.path.getsize(p) for p in input_paths if os.path.isfile(p))

        images = [_open_corrected(p) for p in input_paths]

        if n == 2:
            canvas = self._layout_2(images, background_color)
        else:
            canvas = self._layout_3(images, background_color)

        if max_output_side_px > 0:
            mw, mh = canvas.size
            if max(mw, mh) > max_output_side_px:
                ratio = max_output_side_px / max(mw, mh)
                canvas = canvas.resize(
                    (int(mw * ratio), int(mh * ratio)),
                    Image.Resampling.LANCZOS,
                )

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        fmt = output_format.lower()
        if fmt == "jpeg":
            canvas.save(output_path, "JPEG", quality=jpeg_quality, optimize=True)
        else:
            canvas.save(output_path, "PNG", optimize=True)

        output_bytes = os.path.getsize(output_path)
        logger.info(
            "photo_merge_done",
            extra={"n": n, "output_path": output_path, "output_bytes": output_bytes},
        )
        return {"input_bytes": input_bytes, "output_bytes": output_bytes}

    def _layout_2(self, images: list[Image.Image], bg_color: str) -> Image.Image:
        """Два фото в ряд. Высота — минимальная из двух."""
        target_h = min(img.size[1] for img in images)
        resized = [_resize_to_height(img, target_h) for img in images]
        total_w = sum(img.size[0] for img in resized)
        rgb = _hex_to_rgb(bg_color)
        canvas = Image.new("RGB", (total_w, target_h), rgb)
        x = 0
        for img in resized:
            canvas.paste(img, (x, 0))
            x += img.size[0]
        return canvas

    def _layout_3(self, images: list[Image.Image], bg_color: str) -> Image.Image:
        """3 фото: две сверху в ряд, одна снизу по центру."""
        top_h = min(images[0].size[1], images[1].size[1])
        top_imgs = [_resize_to_height(img, top_h) for img in images[:2]]
        top_w = sum(img.size[0] for img in top_imgs)

        bot_img = images[2]
        bot_w_orig, bot_h_orig = bot_img.size
        # Подогнать нижнее фото по ширине под суммарную ширину верхних (downscale only)
        if bot_w_orig > top_w:
            ratio = top_w / bot_w_orig
            bot_img = bot_img.resize(
                (top_w, int(bot_h_orig * ratio)), Image.Resampling.LANCZOS
            )
        bot_w, bot_h = bot_img.size

        total_h = top_h + bot_h
        rgb = _hex_to_rgb(bg_color)
        canvas = Image.new("RGB", (top_w, total_h), rgb)
        x = 0
        for img in top_imgs:
            canvas.paste(img, (x, 0))
            x += img.size[0]
        # Центрирование нижнего фото
        bot_x = (top_w - bot_w) // 2
        canvas.paste(bot_img, (bot_x, top_h))
        return canvas
