from unittest.mock import MagicMock


def test_master_prompt_payload_preview_returns_sanitized_request(monkeypatch):
    from app.api.routes import admin as admin_route

    class _FakeSettingsService:
        def __init__(self, _db):
            pass

        def as_dict(self):
            base = {
                "prompt_input": "INPUT BLOCK",
                "prompt_input_enabled": True,
                "prompt_task": "TASK BLOCK",
                "prompt_task_enabled": True,
                "prompt_identity_transfer": "",
                "prompt_identity_transfer_enabled": False,
                "safety_constraints": "",
                "safety_constraints_enabled": False,
                "default_model": "gemini-3.1-flash-image-preview",
                "default_size": "768x1024",
                "default_format": "png",
                "default_temperature": 0.0,
                "default_image_size_tier": "4K",
                "default_aspect_ratio": "3:4",
                "default_top_p": 0.1,
                "default_seed": 42,
                "default_candidate_count": 4,
                "default_media_resolution": "HIGH",
                "default_thinking_config": {"thinking_level": "HIGH"},
            }
            return {"preview": dict(base), "release": dict(base)}

        def normalize_profile_payload(self, raw):
            return raw

    monkeypatch.setattr(admin_route, "GenerationPromptSettingsService", _FakeSettingsService)

    out = admin_route.master_prompt_payload_preview(
        payload={
            "profile": "release",
            "input_files": [{"mime_type": "image/png", "size_bytes": 1234}],
        },
        db=MagicMock(),
    )

    sent_request = out["sent_request"]
    generation_cfg = sent_request["generationConfig"]
    parts = sent_request["contents"][0]["parts"]

    assert sent_request["model"] == "gemini-3.1-flash-image-preview"
    assert generation_cfg["temperature"] == 0.0
    assert generation_cfg["candidateCount"] == 1
    assert "mediaResolution" not in generation_cfg  # model does not support mediaResolution
    assert generation_cfg["imageConfig"]["aspectRatio"] == "3:4"
    assert parts[1]["inlineData"]["data"] == "[REDACTED, 1234 bytes]"
    assert any(d["field"] == "generationConfig.candidateCount" and d["status"] == "forced" for d in out["diagnostics"])


def test_master_prompt_payload_preview_marks_runtime_seed_when_missing(monkeypatch):
    from app.api.routes import admin as admin_route

    class _FakeSettingsService:
        def __init__(self, _db):
            pass

        def as_dict(self):
            base = {
                "prompt_input": "",
                "prompt_input_enabled": True,
                "prompt_task": "",
                "prompt_task_enabled": True,
                "prompt_identity_transfer": "",
                "prompt_identity_transfer_enabled": False,
                "safety_constraints": "",
                "safety_constraints_enabled": False,
                "default_model": "gemini-3.1-flash-image-preview",
                "default_size": "768x1024",
                "default_format": "png",
                "default_temperature": 0.5,
                "default_image_size_tier": "4K",
                "default_aspect_ratio": "3:4",
                "default_top_p": None,
                "default_seed": None,
                "default_candidate_count": 1,
                "default_media_resolution": None,
                "default_thinking_config": None,
            }
            return {"preview": dict(base), "release": dict(base)}

        def normalize_profile_payload(self, raw):
            return raw

    monkeypatch.setattr(admin_route, "GenerationPromptSettingsService", _FakeSettingsService)

    out = admin_route.master_prompt_payload_preview(payload={"profile": "release"}, db=MagicMock())
    generation_cfg = out["sent_request"]["generationConfig"]
    assert generation_cfg["seed"] == "[RUNTIME_RANDOM_A_B_C_IF_TAKE_FLOW]"
    assert any(d["field"] == "generationConfig.seed" and d["status"] == "info" for d in out["diagnostics"])
