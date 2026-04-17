from unittest.mock import MagicMock

from app.workers.tasks.generate_take import (
    _build_take_variant_seeds,
    _resolve_generation_config,
    _resolve_take_variant_sampling,
)
from app.workers.tasks.generation_v2 import _resolve_job_generation_config


def test_build_take_variant_seeds_with_base_seed():
    assert _build_take_variant_seeds(42) == {"A": 42, "B": 43, "C": 44}


def test_build_take_variant_seeds_without_base_seed(monkeypatch):
    seq = iter([100, 200, 300])
    monkeypatch.setattr("app.workers.tasks.generate_take.random.randint", lambda *_args, **_kwargs: next(seq))
    assert _build_take_variant_seeds(None) == {"A": 100, "B": 200, "C": 300}


def test_resolve_generation_config_prefers_trend_over_master_defaults():
    trend = MagicMock()
    trend.prompt_aspect_ratio = "4:5"
    trend.prompt_media_resolution = "HIGH"
    trend.prompt_thinking_config = {"thinking_level": "MEDIUM"}
    trend.prompt_top_p = 0.25
    trend.prompt_seed = 123

    out = _resolve_generation_config(
        trend=trend,
        effective_release={
            "default_aspect_ratio": "3:4",
            "default_media_resolution": "LOW",
            "default_thinking_config": {"thinking_budget": 16},
            "default_top_p": 0.9,
            "default_seed": 7,
        },
        model="gemini-3.1-flash-image-preview",
        size="1024x576",
        prefer_size_aspect_ratio=True,
    )
    assert out["aspect_ratio"] == "4:5"
    assert out["media_resolution"] == "HIGH"
    assert out["thinking_config"] == {"thinking_level": "MEDIUM"}
    assert out["top_p"] == 0.25
    assert out["base_seed"] == 123
    assert out["candidate_count"] == 1


def test_resolve_job_generation_config_uses_master_defaults_when_trend_empty():
    out = _resolve_job_generation_config(
        trend=None,
        effective_release={
            "default_aspect_ratio": "3:2",
            "default_media_resolution": "LOW",
            "default_thinking_config": {"thinking_budget": 32},
            "default_top_p": 0.15,
            "default_seed": 99,
        },
        model="gemini-2.5-flash-image",
        size="768x1024",
        prefer_size_aspect_ratio=False,
    )
    assert out["aspect_ratio"] == "3:2"
    assert out["media_resolution"] == "LOW"
    assert out["thinking_config"] == {"thinking_budget": 32}
    assert out["top_p"] == 0.15
    assert out["seed"] == 99
    assert out["candidate_count"] == 1


def test_resolve_generation_config_prefers_explicit_size_ratio_when_no_trend_aspect():
    trend = MagicMock()
    trend.prompt_aspect_ratio = None
    trend.prompt_media_resolution = None
    trend.prompt_thinking_config = None
    trend.prompt_top_p = None
    trend.prompt_seed = None

    out = _resolve_generation_config(
        trend=trend,
        effective_release={"default_aspect_ratio": "3:4"},
        model="gemini-3.1-flash-image-preview",
        size="1024x576",
        prefer_size_aspect_ratio=True,
    )
    assert out["aspect_ratio"] == "16:9"


def test_resolve_generation_config_falls_back_to_1_1_for_invalid_explicit_size():
    trend = MagicMock()
    trend.prompt_aspect_ratio = None
    trend.prompt_media_resolution = None
    trend.prompt_thinking_config = None
    trend.prompt_top_p = None
    trend.prompt_seed = None

    out = _resolve_generation_config(
        trend=trend,
        effective_release={"default_aspect_ratio": "3:4"},
        model="gemini-3.1-flash-image-preview",
        size="bad-size",
        prefer_size_aspect_ratio=True,
    )
    assert out["aspect_ratio"] == "1:1"


def test_resolve_take_variant_sampling_for_trend_uses_master_abc_overrides():
    trend = MagicMock()
    trend.prompt_temperature = None
    trend.prompt_top_p = None

    out = _resolve_take_variant_sampling(
        take_type="TREND",
        trend=trend,
        effective_release={
            "default_temperature_a": 0.2,
            "default_temperature_b": 0.35,
            "default_temperature_c": 0.5,
            "default_top_p_a": 0.1,
            "default_top_p_b": 0.2,
            "default_top_p_c": 0.3,
        },
        base_temperature=0.7,
        base_top_p=0.9,
    )
    assert out["A"] == {"temperature": 0.2, "top_p": 0.1}
    assert out["B"] == {"temperature": 0.35, "top_p": 0.2}
    assert out["C"] == {"temperature": 0.5, "top_p": 0.3}


def test_resolve_take_variant_sampling_for_trend_keeps_trend_overrides():
    trend = MagicMock()
    trend.prompt_temperature = 0.4
    trend.prompt_top_p = 0.25

    out = _resolve_take_variant_sampling(
        take_type="TREND",
        trend=trend,
        effective_release={
            "default_temperature_a": 0.1,
            "default_temperature_b": 0.2,
            "default_temperature_c": 0.3,
            "default_top_p_a": 0.1,
            "default_top_p_b": 0.2,
            "default_top_p_c": 0.3,
        },
        base_temperature=0.4,
        base_top_p=0.25,
    )
    assert out["A"] == {"temperature": 0.4, "top_p": 0.25}
    assert out["B"] == {"temperature": 0.4, "top_p": 0.25}
    assert out["C"] == {"temperature": 0.4, "top_p": 0.25}


def test_resolve_take_variant_sampling_for_copy_keeps_copy_temperatures():
    out = _resolve_take_variant_sampling(
        take_type="COPY",
        trend=None,
        effective_release={},
        base_temperature=0.7,
        base_top_p=0.15,
    )
    assert out["A"]["temperature"] == 0.2
    assert out["B"]["temperature"] == 0.35
    assert out["C"]["temperature"] == 0.5
    assert out["A"]["top_p"] == 0.15
