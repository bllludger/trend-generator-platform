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


# Фиксированный user-текст для Vision (флоу «Сделать такую же»). user_prompt из БД не используется.
_COPY_STYLE_USER_MESSAGE = (
    "Image 1 = reference photo (analyze scene and style from this). "
    "Image 2 = identity photo (this person's face). "
    "Analyze the reference and output exactly in the format specified in the system prompt."
)


def analyze_for_copy_style(reference_path: str, identity_path: str) -> str:
    """
    Анализирует референс + identity фото. Возвращает текст в формате SCENE / STYLE / META
    для последующего парсинга и сборки промпта как у трендов.
    Оба изображения отправляются в GPT в одном запросе.

    Args:
        reference_path: путь к референсному изображению (сцена/стиль)
        identity_path: путь к фото пользователя (лицо)

    Returns:
        Сырой текст ответа (SCENE: ... --- STYLE: ... --- META: ...)

    Raises:
        ValueError: если файл не найден или API недоступен
    """
    ref_path = Path(reference_path)
    id_path = Path(identity_path)
    if not ref_path.exists():
        raise ValueError(f"Reference image not found: {reference_path}")
    if not id_path.exists():
        raise ValueError(f"Identity image not found: {identity_path}")

    opts = _get_copy_style_settings()
    model = opts["model"]
    system_prompt = opts["system_prompt"]
    max_tokens = opts["max_tokens"]

    with open(ref_path, "rb") as f:
        ref_b64 = base64.b64encode(f.read()).decode("utf-8")
    with open(id_path, "rb") as f:
        id_b64 = base64.b64encode(f.read()).decode("utf-8")

    ref_mime = _get_mime_type(str(ref_path))
    id_mime = _get_mime_type(str(id_path))

    user_content = [
        {"type": "text", "text": _COPY_STYLE_USER_MESSAGE},
        {"type": "image_url", "image_url": {"url": f"data:{ref_mime};base64,{ref_b64}"}},
        {"type": "image_url", "image_url": {"url": f"data:{id_mime};base64,{id_b64}"}},
    ]

    client = OpenAI(api_key=settings.openai_api_key)
    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
    try:
        try:
            response = client.chat.completions.create(**kwargs, max_completion_tokens=max_tokens)
        except TypeError:
            response = client.chat.completions.create(**kwargs, max_tokens=max_tokens)
    except Exception as e:
        logger.exception("Vision API error (copy_style)", extra={"reference_path": reference_path, "identity_path": identity_path})
        raise ValueError(f"Ошибка анализа изображений: {e}") from e

    content = response.choices[0].message.content
    if not content or not content.strip():
        raise ValueError("Пустой ответ от модели")

    prompt = content.strip()
    # Извлекаем содержимое code block если модель обернула вывод в ```...``` или ```python\n...```
    if "```" in prompt:
        start = prompt.find("```")
        end = prompt.find("```", start + 3)
        if end != -1:
            inner = prompt[start + 3 : end].strip()
            # Убираем опциональную первую строку с языком (python, text и т.д.)
            if "\n" in inner and inner.split("\n", 1)[0].strip().lower() in ("python", "text", "json"):
                inner = inner.split("\n", 1)[1].strip()
            prompt = inner if inner else prompt.strip()
        else:
            prompt = prompt.split("```", 1)[-1].strip() or prompt.strip()
    if not prompt or not prompt.strip():
        raise ValueError("Пустой ответ от модели после извлечения промпта")
    prompt = prompt.strip()
    if len(prompt) > 4000:
        prompt = prompt[:4000]

    logger.info("copy_style_analyzed", extra={"prompt_len": len(prompt)})
    return prompt
