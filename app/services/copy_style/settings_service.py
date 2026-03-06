"""Сервис настроек «Сделать такую же»: читает/пишет только в БД. Дефолты — в миграции 011, не дублируются здесь."""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.copy_style_settings import CopyStyleSettings

# Только для пустых полей (если миграция не заполнила или кто-то очистил). Nano Banana Prompt Builder.
_FALLBACK_SYSTEM = """SYSTEM PROMPT - NANO BANANA PROMPT BUILDER (IDENTITY-LOCKED PHOTOSESSION, ENGLISH ONLY, COMPACT)

You analyze the user-provided images and output ONE Nano Banana prompt.

MODE SELECTION
- If the user provides a SCENE_REFERENCE image: copy that scene 1:1 (layout, object count, positions, colors, materials, relative sizes).
- If no SCENE_REFERENCE is provided: use the user SCENE text; if missing, keep the original identity photo scene.

PRIORITY (STRICT)
face unchanged > hair/head look > person count > scene accuracy (if reference) > pose/expression > wardrobe > style

IDENTITY LOCK (ABSOLUTE)
- Identity source = user IDENTITY photo only.
- Mandatory line (verbatim) must appear in final prompt:
  "The face must remain strictly unchanged. STRICTLY."
- Do not beautify or alter facial geometry/proportions/age markers/distinctive features.
- Keep hair color + general hairstyle silhouette and head look from IDENTITY photo (use ambiguous if not visible).
- Person count = 1. No identity merging.

SCENE COPY RULE (1:1 WHEN REFERENCE PROVIDED)
- Treat SCENE_REFERENCE as scene/composition source only, never as identity.
- Recreate the scene with maximum fidelity:
  object list + exact counts + approximate positions (left/right/top/bottom/foreground/background) + relative sizes + dominant colors + occlusions.
- Do not add/remove objects; if something is unclear, label ambiguous and choose the least-creative default.

WHAT MAY CHANGE (DEFAULT)
- Wardrobe may change to the user WARDROBE spec (if none, keep original).
- Pose/expression stays as identity photo unless user requests a different pose.

EVIDENCE RULE
- Describe identity/pose only from visible evidence.
- Unknowns must be labeled: ambiguous / partially_visible / occluded / not_visible.
- Do not invent brands, text, logos.

LANGUAGE LOCK (ABSOLUTE)
- Output ENGLISH ONLY.

OUTPUT RULES
- Output exactly ONE code block and nothing else.
- The code block contains ONE final Nano Banana prompt using the template below.
- Target length: 1000-1700 characters.

FINAL PROMPT TEMPLATE (FILL)

[GOAL]
type: edit
intent: "Identity-locked photoshoot: keep the same person and face from the identity photo; copy the target scene with high fidelity; apply requested wardrobe if provided."

[IDENTITY]
identity_lock: on
mandatory: "The face must remain strictly unchanged. STRICTLY."
keep: "facial geometry, proportions, age markers, distinctive features; hair color + hairstyle silhouette"
person_count: 1
visibility_notes: "<notes using ambiguous/partially_visible/occluded/not_visible>"

[SCENE SOURCE]
scene_reference_used: "<yes/no>"
rule: "If yes: copy scene 1:1 from SCENE_REFERENCE (layout, counts, positions, colors). If no: follow user SCENE text or keep original."

[SUBJECT - FROM IDENTITY PHOTO]
pose_expression: "<from image or ambiguous>"
hair: "<visible or ambiguous>"
accessories: "<visible or none>"

[SCENE - COPY WITH FIDELITY]
objects_inventory: "<bullet-like inline list: object:type x count; color; key attributes>"
layout_map: "<foreground/midground/background + left/center/right + occlusions>"
background: "<materials/colors/lighting cues from reference or text>"

[TARGET WARDROBE - FROM USER REQUEST]
wardrobe: "<replace outfit with ... | keep original outfit>"
wardrobe_constraints: "<optional: do not keep original outfit>"

[COMPOSITION | LIGHT | STYLE | OUTPUT]
composition: "<shot/angle/framing/dof from reference or user>"
lighting_color: "<from reference or user>"
style: "<e.g., photoreal fashion editorial>"

[NEGATIVE - LIGHT]
avoid: "extra people, any face change, beauty retouch, altered facial geometry, plastic skin, deformed hands, extra fingers, blur, low-res, watermark, any text/logos, added objects, missing objects"
"""
_FALLBACK_USER = "You receive two images: Image 1 = SCENE_REFERENCE (copy this scene 1:1). Image 2 = IDENTITY (this person's face and look must be preserved). Analyze both and output exactly ONE code block containing the final Nano Banana prompt as specified in the system prompt. No explanations, no extra text."
_FALLBACK_INSTRUCTION_3 = (
    "Attached images order: (1) Style/scene reference to replicate. "
    "(2) Use this person's face for the woman/female character. "
    "(3) Use this person's face for the man/male character. "
    "Generate the scene in the described style with these two faces."
)
_FALLBACK_INSTRUCTION_2 = (
    "Attached images order: (1) Use this face for the woman/female character. "
    "(2) Use this face for the man/male character. Generate the scene with these faces."
)
# Дефолт системного префикса для генерации (флоу «Сделать такую же») — если в БД пусто
_FALLBACK_GENERATION_SYSTEM_PREFIX = (
    "You are an image generation system (Nano Banana / Gemini image editing mode). "
    "Follow instructions exactly. No explanations, no captions, no intermediate steps. "
    "TREND (text) defines style and scene. Attached images define who must appear. "
    "Preserve identity, count, and placement of people from the input images. "
    "Return one final image only."
)


class CopyStyleSettingsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self) -> CopyStyleSettings | None:
        return self.db.query(CopyStyleSettings).filter(CopyStyleSettings.id == 1).first()

    def get_or_create(self) -> CopyStyleSettings:
        row = self.get()
        if row:
            return row
        row = CopyStyleSettings(
            id=1,
            model=getattr(settings, "openai_vision_model", "gpt-4o"),
            system_prompt="",
            user_prompt="",
            max_tokens=1536,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_effective(self) -> dict[str, Any]:
        """Настройки для vision_analyzer и воркера. Единая точка — только БД; пустые поля — fallback."""
        row = self.get_or_create()
        sp = (row.system_prompt or "").strip()
        up = (row.user_prompt or "").strip()
        suffix = (getattr(row, "prompt_suffix", None) or "").strip()
        instr_3 = (getattr(row, "prompt_instruction_3_images", None) or "").strip()
        instr_2 = (getattr(row, "prompt_instruction_2_images", None) or "").strip()
        gen_prefix = (getattr(row, "generation_system_prompt_prefix", None) or "").strip()
        gen_neg = (getattr(row, "generation_negative_prompt", None) or "").strip()
        gen_safety = (getattr(row, "generation_safety_constraints", None) or "").strip() or "no text generation, no chat."
        gen_constraints = (getattr(row, "generation_image_constraints_template", None) or "").strip() or "size={size}, format={format}"
        gen_size = (getattr(row, "generation_default_size", None) or "").strip() or "1024x1024"
        gen_fmt = (getattr(row, "generation_default_format", None) or "").strip() or "png"
        gen_model = (getattr(row, "generation_default_model", None) or "").strip() or getattr(settings, "gemini_image_model", "gemini-2.5-flash-image")
        return {
            "model": (row.model or "").strip() or getattr(settings, "openai_vision_model", "gpt-4o"),
            "system_prompt": sp or _FALLBACK_SYSTEM,
            "user_prompt": up or _FALLBACK_USER,
            "max_tokens": max(256, row.max_tokens or 1536),
            "prompt_suffix": suffix,
            "prompt_instruction_3_images": instr_3 or _FALLBACK_INSTRUCTION_3,
            "prompt_instruction_2_images": instr_2 or _FALLBACK_INSTRUCTION_2,
            "generation_system_prompt_prefix": gen_prefix or _FALLBACK_GENERATION_SYSTEM_PREFIX,
            "generation_negative_prompt": gen_neg,
            "generation_safety_constraints": gen_safety,
            "generation_image_constraints_template": gen_constraints,
            "generation_default_size": gen_size,
            "generation_default_format": gen_fmt,
            "generation_default_model": gen_model,
        }

    def as_dict(self) -> dict[str, Any]:
        """Для админ API: то, что в БД (пустые — fallback в форме). Единая точка — админка «Сделать такую же»."""
        row = self.get_or_create()
        sp = (row.system_prompt or "").strip()
        up = (row.user_prompt or "").strip()
        suffix = (getattr(row, "prompt_suffix", None) or "").strip()
        instr_3 = (getattr(row, "prompt_instruction_3_images", None) or "").strip()
        instr_2 = (getattr(row, "prompt_instruction_2_images", None) or "").strip()
        gen_prefix = (getattr(row, "generation_system_prompt_prefix", None) or "").strip()
        gen_neg = (getattr(row, "generation_negative_prompt", None) or "").strip()
        gen_safety = (getattr(row, "generation_safety_constraints", None) or "").strip()
        gen_constraints = (getattr(row, "generation_image_constraints_template", None) or "").strip()
        gen_size = (getattr(row, "generation_default_size", None) or "").strip()
        gen_fmt = (getattr(row, "generation_default_format", None) or "").strip()
        gen_model = (getattr(row, "generation_default_model", None) or "").strip()
        return {
            "model": (row.model or "").strip() or getattr(settings, "openai_vision_model", "gpt-4o"),
            "system_prompt": sp or _FALLBACK_SYSTEM,
            "user_prompt": up or _FALLBACK_USER,
            "max_tokens": max(256, row.max_tokens or 1536),
            "prompt_suffix": suffix,
            "prompt_instruction_3_images": instr_3 or _FALLBACK_INSTRUCTION_3,
            "prompt_instruction_2_images": instr_2 or _FALLBACK_INSTRUCTION_2,
            "generation_system_prompt_prefix": gen_prefix or _FALLBACK_GENERATION_SYSTEM_PREFIX,
            "generation_negative_prompt": gen_neg,
            "generation_safety_constraints": gen_safety or "no text generation, no chat.",
            "generation_image_constraints_template": gen_constraints or "size={size}, format={format}",
            "generation_default_size": gen_size or "1024x1024",
            "generation_default_format": gen_fmt or "png",
            "generation_default_model": gen_model or getattr(settings, "gemini_image_model", "gemini-2.5-flash-image"),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def update(self, data: dict[str, Any]) -> dict[str, Any]:
        row = self.get_or_create()
        if "model" in data:
            row.model = (str(data["model"]) or "").strip() or "gpt-4o"
        if "system_prompt" in data:
            raw = data["system_prompt"]
            row.system_prompt = "" if raw is None else str(raw)
        if "user_prompt" in data:
            raw = data["user_prompt"]
            row.user_prompt = "" if raw is None else str(raw)
        if "max_tokens" in data and data["max_tokens"] is not None:
            try:
                n = int(data["max_tokens"])
                row.max_tokens = max(256, n)
            except (TypeError, ValueError):
                pass
        if "prompt_suffix" in data:
            raw = data["prompt_suffix"]
            row.prompt_suffix = "" if raw is None else str(raw)
        if "prompt_instruction_3_images" in data:
            raw = data["prompt_instruction_3_images"]
            row.prompt_instruction_3_images = "" if raw is None else str(raw)
        if "prompt_instruction_2_images" in data:
            raw = data["prompt_instruction_2_images"]
            row.prompt_instruction_2_images = "" if raw is None else str(raw)
        if "generation_system_prompt_prefix" in data:
            row.generation_system_prompt_prefix = "" if data["generation_system_prompt_prefix"] is None else str(data["generation_system_prompt_prefix"])
        if "generation_negative_prompt" in data:
            row.generation_negative_prompt = "" if data["generation_negative_prompt"] is None else str(data["generation_negative_prompt"])
        if "generation_safety_constraints" in data:
            raw = data["generation_safety_constraints"]
            row.generation_safety_constraints = "" if raw is None else str(raw)
        if "generation_image_constraints_template" in data:
            raw = data["generation_image_constraints_template"]
            row.generation_image_constraints_template = "" if raw is None else str(raw)
        if "generation_default_size" in data and data["generation_default_size"] is not None:
            row.generation_default_size = (str(data["generation_default_size"]) or "1024x1024").strip() or "1024x1024"
        if "generation_default_format" in data and data["generation_default_format"] is not None:
            row.generation_default_format = (str(data["generation_default_format"]) or "png").strip() or "png"
        if "generation_default_model" in data:
            row.generation_default_model = "" if data["generation_default_model"] is None else str(data["generation_default_model"]).strip()
        row.updated_at = datetime.now(timezone.utc)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return self.as_dict()
