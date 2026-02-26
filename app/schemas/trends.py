from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TrendOut(BaseModel):
    id: str
    name: str
    emoji: str
    description: str
    max_images: int
    enabled: bool
    order_index: int


class TrendAdminIn(BaseModel):
    model_config = ConfigDict(extra="ignore")  # фронт может присылать id, deeplink, has_example и т.д.

    name: str
    emoji: str
    description: str
    scene_prompt: str = ""
    style_preset: dict | str | None = None  # JSON-объект или строка; null от фронта → в коде приводим к {}
    negative_scene: str = ""
    composition_prompt: str | None = None  # опционально: [COMPOSITION]; если пусто — из Transfer Policy
    subject_mode: str = "face"  # face | head_torso | full_body
    framing_hint: str = "portrait"  # close_up | portrait | half_body | full_body
    max_images: int = 1
    enabled: bool = True
    order_index: int = 0

    @field_validator("order_index", mode="before")
    @classmethod
    def coerce_order_index(cls, v: Any) -> int:
        if v is None:
            return 0
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            return int(v)
        if isinstance(v, str):
            try:
                return int(float(v))
            except (ValueError, TypeError):
                pass
        return 0

    @field_validator("max_images", mode="before")
    @classmethod
    def coerce_max_images(cls, v: Any) -> int:
        if v is None:
            return 1
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            return int(v)
        if isinstance(v, str):
            try:
                return int(float(v))
            except (ValueError, TypeError):
                pass
        return 1

    # legacy (скрыты в UI, только если scene_prompt пуст)
    system_prompt: str = ""
    subject_prompt: str = ""
    negative_prompt: str = ""
    # Playground 1:1 — когда заданы, воркер собирает промпт из секций
    prompt_sections: list[dict[str, Any]] | None = None
    prompt_model: str | None = None
    prompt_size: str | None = None
    prompt_format: str | None = None
    prompt_aspect_ratio: str | None = None
    prompt_image_size_tier: str | None = None
    prompt_temperature: float | None = None
    prompt_seed: int | float | None = None  # фронт/JSON может прислать float — при сохранении в БД приводим к int


def require_prompt(payload: TrendAdminIn) -> None:
    """Промпты не пустые: либо prompt_sections (Playground), либо scene_prompt/system_prompt."""
    has_sections = payload.prompt_sections and len(payload.prompt_sections) > 0
    scene = (payload.scene_prompt or "").strip()
    legacy = (payload.system_prompt or "").strip()
    if has_sections or scene or legacy:
        return
    raise ValueError(
        "Заполните Prompt Sections (вкладка Промпты) или сцену (scene_prompt). Промпты оставлять пустыми нельзя."
    )


class TrendAdminOut(TrendAdminIn):
    id: str
    has_example: bool = False  # пример результата (показ в боте)
    deeplink: str | None = None  # ссылка «Попробовать этот тренд» (если задан telegram_bot_username)


class TrendDeeplinkOut(BaseModel):
    """Один тренд с диплинком для списка GET /admin/trends/deeplinks."""
    trend_id: str
    trend_name: str
    deeplink: str
