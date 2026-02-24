"""
Обёртка над app.utils.watermark: вызов apply_watermark с текстом из paywall config.
"""
from __future__ import annotations

import logging

from app.paywall.config import get_watermark_text
from app.utils.watermark import apply_watermark as _apply_watermark

logger = logging.getLogger(__name__)


def apply_watermark(image_path: str, output_path: str) -> str:
    """Наложить watermark на изображение; текст из конфига."""
    text = get_watermark_text()
    return _apply_watermark(image_path, output_path, text=text)
