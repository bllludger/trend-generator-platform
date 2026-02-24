"""
Execution: prepare_delivery(access_decision, raw_path, storage_dir, job_id, attempt) -> DeliveryResult.
При show_preview: копирует raw в ..._original, генерирует ..._preview с watermark.
Имена с attempt — иммутабельные (retry/regen не перезаписывают).
"""
from __future__ import annotations

import logging
import os
import shutil

from app.paywall.models import AccessDecision, DeliveryResult, UnlockOptions
from app.paywall.watermark import apply_watermark

logger = logging.getLogger(__name__)


def prepare_delivery(
    access_decision: AccessDecision,
    raw_file_path: str,
    storage_dir: str,
    job_id: str,
    attempt: int | str,
) -> DeliveryResult:
    """
    По решению access при необходимости накладывает watermark, сохраняет файлы
    с именами {job_id}_{attempt}_preview.{ext} / _original.{ext}; возвращает пути и флаги.
    """
    if not os.path.isfile(raw_file_path):
        raise FileNotFoundError(f"Raw file not found: {raw_file_path}")

    ext = _get_ext(raw_file_path)
    base = f"{job_id}_{attempt}"
    original_path = os.path.join(storage_dir, f"{base}_original{ext}")
    preview_path = os.path.join(storage_dir, f"{base}_preview{ext}")

    if access_decision.show_preview:
        os.makedirs(storage_dir, exist_ok=True)
        shutil.copy2(raw_file_path, original_path)
        apply_watermark(raw_file_path, preview_path)
        logger.info(
            "paywall_delivery_preview",
            extra={"job_id": job_id, "attempt": attempt, "preview": preview_path, "original": original_path},
        )
        return DeliveryResult(
            preview_path=preview_path,
            original_path=original_path,
            is_preview=True,
            unlock_options=access_decision.unlock_options,
        )

    # Full: отдаём сырой файл как оригинал (не копируем, он уже на диске)
    return DeliveryResult(
        preview_path=None,
        original_path=raw_file_path,
        is_preview=False,
        unlock_options=access_decision.unlock_options,
    )


def _get_ext(path: str) -> str:
    e = os.path.splitext(path)[1].lower()
    return e if e in (".png", ".jpg", ".jpeg", ".webp") else ".png"
