"""
LLM Vision service: анализирует референсное фото и генерирует промпт для 1:1 копирования.
Использует модель и промпты из настроек «Сделать такую же» (админка) или дефолты из кода.
"""
import base64
import logging
from pathlib import Path

from openai import OpenAI

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.copy_style.settings_service import CopyStyleSettingsService

logger = logging.getLogger("llm.vision")


def _get_mime_type(path: str) -> str:
    """Определить MIME по расширению."""
    ext = Path(path).suffix.lower()
    return {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(
        ext.lstrip("."), "image/jpeg"
    )


def _get_copy_style_settings() -> dict:
    """Читает настройки «Сделать такую же» из БД (модель, промпты, max_tokens)."""
    db = SessionLocal()
    try:
        return CopyStyleSettingsService(db).get_effective()
    finally:
        db.close()


def analyze_reference_image(image_path: str) -> str:
    """
    Анализирует референсное изображение и возвращает промпт для копирования стиля.
    Модель и промпты берутся из настроек в админке (таблица copy_style_settings).

    Args:
        image_path: путь к локальному файлу изображения

    Returns:
        Текст промпта на английском для генерации

    Raises:
        ValueError: если файл не найден или API недоступен
    """
    path = Path(image_path)
    if not path.exists():
        raise ValueError(f"Image not found: {image_path}")

    opts = _get_copy_style_settings()
    model = opts["model"]
    system_prompt = opts["system_prompt"]
    user_prompt = opts["user_prompt"]
    max_tokens = opts["max_tokens"]

    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    mime = _get_mime_type(str(path))
    client = OpenAI(api_key=settings.openai_api_key)

    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                ],
            },
        ],
    }
    # Новые модели (gpt-4o, gpt-5.x) требуют max_completion_tokens; старый клиент openai знает только max_tokens
    try:
        try:
            response = client.chat.completions.create(**kwargs, max_completion_tokens=max_tokens)
        except TypeError:
            response = client.chat.completions.create(**kwargs, max_tokens=max_tokens)
    except Exception as e:
        logger.exception("Vision API error", extra={"image_path": image_path})
        raise ValueError(f"Ошибка анализа изображения: {e}") from e

    content = response.choices[0].message.content
    if not content or not content.strip():
        raise ValueError("Пустой ответ от модели")

    prompt = content.strip()
    if len(prompt) > 2000:
        prompt = prompt[:2000]

    logger.info("reference_analyzed", extra={"prompt_len": len(prompt)})
    return prompt
