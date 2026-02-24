from pydantic import BaseModel


class PromptConfig(BaseModel):
    name: str
    display_name: str | None = None
    trend_id: str | None = None
    system_prompt_prefix: str | None = None
    negative_prompt_prefix: str | None = None
    safety_constraints: str | None = None
    image_constraints_template: str | None = None
    model: str | None = None
    size: str | None = None
    format: str | None = None
    temperature: float | None = None
    system_prompt: str | None = None
    scene_prompt: str | None = None
    subject_prompt: str | None = None
    negative_prompt: str | None = None
    negative_scene: str | None = None
    subject_mode: str | None = None
    framing_hint: str | None = None
    style_preset: dict | str | None = None  # JSON-объект или произвольная строка (как в тренде)


class PromptConfigIn(BaseModel):
    name: str | None = None
    display_name: str | None = None
    trend_id: str | None = None
    system_prompt_prefix: str | None = None
    negative_prompt_prefix: str | None = None
    safety_constraints: str | None = None
    image_constraints_template: str | None = None
    model: str | None = None
    size: str | None = None
    format: str | None = None
    temperature: float | None = None
    system_prompt: str | None = None
    scene_prompt: str | None = None
    subject_prompt: str | None = None
    negative_prompt: str | None = None
    negative_scene: str | None = None
    subject_mode: str | None = None
    framing_hint: str | None = None
    style_preset: dict | str | None = None  # JSON-объект или произвольная строка (как в тренде)


class TrendPromptOut(PromptConfig):
    trend_id: str
