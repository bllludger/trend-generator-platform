"""
Обёртка над app.utils.watermark: вызов apply_watermark с текстом из конфига или переданными параметрами.
"""
from __future__ import annotations

import logging
from typing import Any

from app.paywall.config import get_watermark_text
from app.utils.watermark import apply_watermark as _apply_watermark

logger = logging.getLogger(__name__)


def apply_watermark(
    image_path: str,
    output_path: str,
    text: str | None = None,
    opacity: int | None = None,
    tile_spacing: int | None = None,
    *,
    params: dict[str, Any] | None = None,
) -> str:
    """Наложить watermark на изображение. Параметры из params или из конфига/дефолтов."""
    if params:
        return _apply_watermark(
            image_path,
            output_path,
            text=params.get("text") or get_watermark_text(),
            opacity=params.get("opacity", 60),
            tile_spacing=params.get("tile_spacing", 200),
        )
    kwargs = {}
    if text is not None:
        kwargs["text"] = text
    else:
        kwargs["text"] = get_watermark_text()
    if opacity is not None:
        kwargs["opacity"] = opacity
    else:
        kwargs["opacity"] = 60
    if tile_spacing is not None:
        kwargs["tile_spacing"] = tile_spacing
    else:
        kwargs["tile_spacing"] = 200
    return _apply_watermark(image_path, output_path, **kwargs)
