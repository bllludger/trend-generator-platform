from unittest.mock import MagicMock

from app.services.generation_prompt.settings_service import (
    GenerationPromptSettingsService,
    canonical_gemini_image_model_id,
    clamp_top_p,
    normalize_aspect_ratio,
    normalize_thinking_config,
    size_to_aspect_ratio,
    strip_legacy_master_prompt_boilerplate,
)


def test_canonical_model_maps_legacy_id():
    assert canonical_gemini_image_model_id("gemini-3.1-pro-preview") == "gemini-3-pro-image-preview"


def test_clamp_top_p_bounds():
    assert clamp_top_p(-1) == 0.0
    assert clamp_top_p(2) == 1.0
    assert clamp_top_p(None) is None


def test_normalize_aspect_ratio_fallback():
    assert normalize_aspect_ratio("3:4") == "3:4"
    assert normalize_aspect_ratio("7:5") == "3:4"


def test_size_to_aspect_ratio():
    assert size_to_aspect_ratio("1024x576") == "16:9"
    assert size_to_aspect_ratio("768x1024") == "3:4"
    assert size_to_aspect_ratio("oops", fallback="3:4") == "3:4"


def test_normalize_thinking_config_model_aware():
    # For Gemini 3 Pro image: LOW/HIGH only.
    assert normalize_thinking_config("gemini-3-pro-image-preview", {"thinking_level": "HIGH"}) == {"thinking_level": "HIGH"}
    # Unsupported level for this model falls back to budget when provided.
    assert normalize_thinking_config(
        "gemini-3-pro-image-preview",
        {"thinking_level": "MEDIUM", "thinking_budget": 32},
    ) == {"thinking_budget": 32}


def test_strip_legacy_master_prompt_boilerplate_removes_templates():
    legacy = (
        "IMAGE_1 = trend reference (scene/style). IMAGE_2 = user photo (preserve this identity in output).\n\n"
        "Generate a single image: apply the scene and style from the trend to the subject from the user photo.\n\n"
        "Привет, помоги сгенерировать:\n\nKEEP"
    )
    assert strip_legacy_master_prompt_boilerplate(legacy) == "KEEP"


def test_normalize_profile_payload_strips_input_and_clears_task():
    svc = GenerationPromptSettingsService(MagicMock())
    out = svc.normalize_profile_payload(
        {
            "prompt_input": "Привет, помоги сгенерировать:\nReal",
            "prompt_task": "Generate a single image: apply the scene and style from the trend to the subject from the user photo.",
        }
    )
    assert out["prompt_task"] == ""
    assert out["prompt_input"] == "Real"


def test_service_normalize_profile_payload_applies_new_defaults():
    svc = GenerationPromptSettingsService(MagicMock())
    out = svc.normalize_profile_payload(
        {
            "default_model": "gemini-3.1-pro-preview",
            "default_top_p": 2,
            "default_top_p_a": -1,
            "default_top_p_b": 1.5,
            "default_top_p_c": "",
            "default_temperature_a": -1,
            "default_temperature_b": 3,
            "default_temperature_c": "",
            "default_candidate_count": 9,
            "default_aspect_ratio": "invalid",
            "default_thinking_config": {"thinking_level": "HIGH"},
        }
    )
    assert out["default_model"] == "gemini-3-pro-image-preview"
    assert out["default_top_p"] == 1.0
    assert out["default_top_p_a"] == 0.0
    assert out["default_top_p_b"] == 1.0
    assert out["default_top_p_c"] is None
    assert out["default_temperature_a"] == 0.0
    assert out["default_temperature_b"] == 2.0
    assert out["default_temperature_c"] is None
    assert out["default_candidate_count"] == 4
    assert out["default_aspect_ratio"] == "3:4"
    assert out["default_thinking_config"] == {"thinking_level": "HIGH"}
