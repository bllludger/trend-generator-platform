"""Парсер вывода Vision для флоу «Сделать такую же»: SCENE / STYLE / META."""
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def parse_vision_output(text: str) -> dict[str, Any]:
    """
    Разбирает текст ответа Vision в формате:
        SCENE:
        ...
        ---
        STYLE:
        ...
        ---
        META:
        subject_mode: ...
        framing: ...
        negative: ...
    Возвращает {"scene": str, "style": str, "meta": {"subject_mode": str, "framing": str, "negative": str}}.
    При нарушении формата — fallback: весь текст в scene, style и meta пустые.
    """
    text = (text or "").strip()
    result: dict[str, Any] = {
        "scene": "",
        "style": "",
        "meta": {"subject_mode": "", "framing": "", "negative": ""},
    }
    if not text:
        return result

    parts = re.split(r"\s*---\s*", text)
    scene_raw = ""
    style_raw = ""
    meta_raw = ""

    for part in parts:
        part = part.strip()
        if not part:
            continue
        part_lower = part.lower()
        if part_lower.startswith("scene:"):
            scene_raw = part[6:].strip()
        elif part_lower.startswith("style:"):
            style_raw = part[6:].strip()
        elif part_lower.startswith("meta:"):
            meta_raw = part[5:].strip()

    if not scene_raw and not style_raw and not meta_raw:
        result["scene"] = text
        logger.warning("copy_style_parser_fallback", extra={"reason": "no_blocks_found", "text_len": len(text)})
        return result

    result["scene"] = scene_raw
    result["style"] = style_raw

    if meta_raw:
        meta = result["meta"]
        for line in meta_raw.splitlines():
            line = line.strip()
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip().lower().replace(" ", "_")
                value = value.strip()
                if key == "subject_mode":
                    meta["subject_mode"] = value
                elif key == "framing":
                    meta["framing"] = value
                elif key == "negative":
                    meta["negative"] = value

    return result
