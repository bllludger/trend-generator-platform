"""
PreviewService — единая точка построения превью для Take и Job.

Правило форматов (preview pipeline):
- Original сохраняется в исходном формате провайдера (PNG от Gemini и т.д.) без изменений.
- Preview строится один раз: original → resize → watermark → encode.
- Preview сохраняется только в JPEG или WebP (настройки политики превью); PNG для превью не используется.
- Наружу до оплаты отдаётся только готовый preview-файл; при повторной отправке в Telegram перекодировка не нужна.
- MIME при отправке в Telegram определяется по фактическому расширению preview-файла.
"""
from __future__ import annotations

import logging
import os
from typing import Literal

from PIL import Image as PILImage
from sqlalchemy.orm import Session

from app.services.app_settings.settings_service import AppSettingsService
from app.utils.watermark import apply_watermark_v2

logger = logging.getLogger(__name__)

Scenario = Literal["take", "job"]


def build_preview(
    original_path: str,
    preview_path: str,
    scenario: Scenario,
    *,
    db: Session,
) -> str:
    """
    Строит превью: даунскейл до max_dim (по сценарию), наложение вотермарка v2, сохранение в формате из БД.

    Args:
        original_path: путь к оригинальному изображению
        preview_path: желаемый путь результата (расширение будет заменено на preview_format из БД)
        scenario: "take" или "job" — выбирает take_preview_max_dim или job_preview_max_dim
        db: сессия БД для чтения app_settings

    Returns:
        Фактический путь к сохранённому превью (с расширением .webp или .jpg)

    Raises:
        FileNotFoundError: если original_path не существует.
    """
    if not os.path.isfile(original_path):
        raise FileNotFoundError(f"Original image not found: {original_path}")

    app_svc = AppSettingsService(db)
    max_dim = app_svc.get_take_preview_max_dim() if scenario == "take" else app_svc.get_job_preview_max_dim()
    preview_format = app_svc.get_preview_format()
    preview_quality = app_svc.get_preview_quality()
    wm_params = app_svc.get_watermark_params()

    # Итоговый путь с правильным расширением
    base, _ = os.path.splitext(preview_path)
    ext = ".webp" if preview_format == "webp" else ".jpg"
    final_preview_path = base + ext

    tmp_path = final_preview_path + ".tmp.png"
    try:
        img = PILImage.open(original_path)
        if max(img.size) > max_dim:
            ratio = max_dim / max(img.size)
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            img = img.resize(new_size, PILImage.LANCZOS)
        img.save(tmp_path, "PNG")
        img.close()

        watermarked = apply_watermark_v2(
            tmp_path,
            text=wm_params.get("text") or "@ai_nanobananastudio_bot",
            opacity=wm_params.get("opacity", 60),
            tile_spacing=wm_params.get("tile_spacing", 200),
            use_contrast=wm_params.get("use_contrast", True),
        )
        if preview_format == "webp":
            watermarked.save(final_preview_path, "WEBP", quality=preview_quality)
        else:
            watermarked.save(final_preview_path, "JPEG", quality=preview_quality)

        logger.info(
            "preview_built",
            extra={"original": original_path, "preview": final_preview_path, "scenario": scenario},
        )
        return final_preview_path
    finally:
        try:
            if os.path.isfile(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            pass


class PreviewService:
    """Единая точка построения превью. Вызов: PreviewService.build_preview(...)."""
    build_preview = staticmethod(build_preview)
