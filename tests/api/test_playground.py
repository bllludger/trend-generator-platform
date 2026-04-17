import base64
import json
from pathlib import Path
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import playground as playground_route
from app.services.image_generation import ImageGenerationError, ImageGenerationResponse

SAMPLE_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+XK7sAAAAASUVORK5CYII="
)


def _make_client(monkeypatch, result: ImageGenerationResponse | None = None, error: Exception | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(playground_route.router)

    app.dependency_overrides[playground_route.get_current_user] = lambda: {"username": "tester"}
    app.dependency_overrides[playground_route.get_db] = lambda: MagicMock()
    monkeypatch.setattr(playground_route, "_ensure_playground_schema", lambda _db: None)

    monkeypatch.setattr(playground_route, "_build_full_prompt_for_playground", lambda _db, _cfg: "Prompt body")
    monkeypatch.setattr(playground_route.ImageProviderFactory, "create_from_settings", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        playground_route,
        "GenerationPromptSettingsService",
        lambda _db: type("GS", (), {"get_effective": lambda self, profile="preview": {"prompt_input": ""}})(),
    )

    if error is not None:
        def _raise(*_args, **_kwargs):
            raise error
        monkeypatch.setattr(playground_route, "generate_with_retry", _raise)
    else:
        monkeypatch.setattr(playground_route, "generate_with_retry", lambda *_args, **_kwargs: result)

    return TestClient(app)


def _config(model: str = "gemini-2.5-flash-image") -> dict:
    return {
        "model": model,
        "temperature": 0.7,
        "top_p": 0.9,
        "candidate_count": 2,
        "media_resolution": "HIGH",
        "thinking_config": {"thinking_budget": 64},
        "format": "png",
        "size": "1024x1024",
        "aspect_ratio": "1:1",
        "sections": [{"id": "1", "label": "Scene", "content": "x", "enabled": True, "order": 0}],
        "variables": {},
        "seed": 42,
        "image_size_tier": "2K",
    }


def test_playground_test_returns_image_urls_and_legacy_image_url(monkeypatch):
    client = _make_client(
        monkeypatch,
        result=ImageGenerationResponse(
            image_content=SAMPLE_PNG_BYTES,
            image_contents=[SAMPLE_PNG_BYTES, SAMPLE_PNG_BYTES],
            model="gemini-3-pro-image-preview",
            provider="gemini",
        ),
    )

    resp = client.post(
        "/admin/playground/test",
        files=[
            ("config", (None, json.dumps(_config("gemini-3-pro-image-preview")), "application/json")),
            ("images", ("a.jpg", b"x", "image/jpeg")),
        ],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body.get("image_urls"), list)
    assert len(body["image_urls"]) == 2
    assert body.get("image_url") == body["image_urls"][0]
    assert body.get("sent_request", {}).get("generationConfig", {}).get("mediaResolution") == "MEDIA_RESOLUTION_HIGH"


def test_playground_test_rejects_too_many_images_for_model(monkeypatch):
    client = _make_client(
        monkeypatch,
        result=ImageGenerationResponse(image_content=SAMPLE_PNG_BYTES, model="gemini-2.5-flash-image", provider="gemini"),
    )
    files = [("config", (None, json.dumps(_config("gemini-2.5-flash-image")), "application/json"))]
    files.extend([("images", (f"{i}.jpg", b"x", "image/jpeg")) for i in range(4)])  # max=3 for 2.5
    resp = client.post("/admin/playground/test", files=files)
    assert resp.status_code == 200
    assert "Too many input files" in (resp.json().get("error") or "")


def test_playground_test_rejects_file_bigger_than_7mb(monkeypatch):
    client = _make_client(
        monkeypatch,
        result=ImageGenerationResponse(image_content=SAMPLE_PNG_BYTES, model="gemini-3-pro-image-preview", provider="gemini"),
    )
    too_big = b"x" * (7 * 1024 * 1024 + 1)
    resp = client.post(
        "/admin/playground/test",
        files=[
            ("config", (None, json.dumps(_config("gemini-3-pro-image-preview")), "application/json")),
            ("images", ("big.jpg", too_big, "image/jpeg")),
        ],
    )
    assert resp.status_code == 200
    assert "File too large" in (resp.json().get("error") or "")


def test_playground_test_supports_legacy_image1(monkeypatch):
    client = _make_client(
        monkeypatch,
        result=ImageGenerationResponse(
            image_content=SAMPLE_PNG_BYTES,
            image_contents=[SAMPLE_PNG_BYTES],
            model="gemini-2.5-flash-image",
            provider="gemini",
        ),
    )
    resp = client.post(
        "/admin/playground/test",
        files=[
            ("config", (None, json.dumps(_config("gemini-2.5-flash-image")), "application/json")),
            ("image1", ("legacy.jpg", b"x", "image/jpeg")),
        ],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body.get("image_urls"), list) and len(body["image_urls"]) == 1
    assert isinstance(body.get("image_url"), str)


def test_playground_test_temp_files_cleaned_on_generation_error(monkeypatch, tmp_path: Path):
    class _Tmp:
        def __init__(self, path: Path):
            self.name = str(path)
            self._f = path.open("wb")

        def write(self, data: bytes):
            self._f.write(data)

        def close(self):
            self._f.close()

    created: list[Path] = []

    def _fake_named_tmp(*_args, **kwargs):
        suffix = kwargs.get("suffix", ".tmp")
        p = tmp_path / f"pg_{len(created)}{suffix}"
        created.append(p)
        return _Tmp(p)

    monkeypatch.setattr(playground_route.tempfile, "NamedTemporaryFile", _fake_named_tmp)

    client = _make_client(
        monkeypatch,
        error=ImageGenerationError("forced"),
    )
    resp = client.post(
        "/admin/playground/test",
        files=[
            ("config", (None, json.dumps(_config("gemini-3-pro-image-preview")), "application/json")),
            ("images", ("a.jpg", b"x", "image/jpeg")),
            ("images", ("b.jpg", b"y", "image/jpeg")),
        ],
    )
    assert resp.status_code == 200
    assert "error" in resp.json()
    assert created, "Expected temp files to be created"
    assert all(not p.exists() for p in created), "Temp files should be removed in finally"


def test_playground_test_rejects_total_upload_size(monkeypatch):
    monkeypatch.setattr(playground_route, "MAX_TOTAL_INLINE_UPLOAD_BYTES", 10)
    client = _make_client(
        monkeypatch,
        result=ImageGenerationResponse(image_content=SAMPLE_PNG_BYTES, model="gemini-3-pro-image-preview", provider="gemini"),
    )
    resp = client.post(
        "/admin/playground/test",
        files=[
            ("config", (None, json.dumps(_config("gemini-3-pro-image-preview")), "application/json")),
            ("images", ("a.jpg", b"123456", "image/jpeg")),
            ("images", ("b.jpg", b"abcdef", "image/jpeg")),
        ],
    )
    assert resp.status_code == 200
    assert "Total upload too large" in (resp.json().get("error") or "")


def test_playground_flash_model_clamps_candidate_and_skips_media_resolution(monkeypatch):
    client = _make_client(
        monkeypatch,
        result=ImageGenerationResponse(
            image_content=SAMPLE_PNG_BYTES,
            image_contents=[SAMPLE_PNG_BYTES],
            model="gemini-3.1-flash-image-preview",
            provider="gemini",
        ),
    )
    cfg = _config("gemini-3.1-flash-image-preview")
    cfg["candidate_count"] = 4
    cfg["media_resolution"] = "MEDIUM"
    resp = client.post(
        "/admin/playground/test",
        files=[
            ("config", (None, json.dumps(cfg), "application/json")),
            ("images", ("a.jpg", b"x", "image/jpeg")),
        ],
    )
    assert resp.status_code == 200
    body = resp.json()
    gc = body.get("sent_request", {}).get("generationConfig", {})
    assert gc.get("candidateCount") == 1
    assert "mediaResolution" not in gc


def test_playground_flash_model_uses_thinking_level(monkeypatch):
    client = _make_client(
        monkeypatch,
        result=ImageGenerationResponse(
            image_content=SAMPLE_PNG_BYTES,
            image_contents=[SAMPLE_PNG_BYTES],
            model="gemini-3.1-flash-image-preview",
            provider="gemini",
        ),
    )
    cfg = _config("gemini-3.1-flash-image-preview")
    cfg["thinking_config"] = {"thinking_level": "high", "thinking_budget": 64}
    resp = client.post(
        "/admin/playground/test",
        files=[
            ("config", (None, json.dumps(cfg), "application/json")),
            ("images", ("a.jpg", b"x", "image/jpeg")),
        ],
    )
    assert resp.status_code == 200
    body = resp.json()
    thinking_cfg = body.get("sent_request", {}).get("generationConfig", {}).get("thinkingConfig", {})
    assert thinking_cfg.get("thinkingLevel") == "HIGH"
    assert "thinkingBudget" not in thinking_cfg


def _batch_test_client(monkeypatch, result: ImageGenerationResponse | None = None, error: Exception | None = None):
    app = FastAPI()
    app.include_router(playground_route.router)
    app.dependency_overrides[playground_route.get_current_user] = lambda: {"username": "tester"}
    mock_db = MagicMock()
    tr = MagicMock()
    tr.id = "trend-1"
    tr.name = "TrendName"
    tr.emoji = "🙂"
    mock_db.query.return_value.filter.return_value.all.return_value = [tr]
    app.dependency_overrides[playground_route.get_db] = lambda: mock_db
    monkeypatch.setattr(playground_route, "_ensure_playground_schema", lambda _db: None)

    def _fake_gs(_db):
        m = MagicMock()
        m.get_effective = lambda profile="preview": {
            "default_model": "gemini-2.5-flash-image",
            "default_temperature": 0.4,
            "default_format": "png",
            "default_size": "1024x1024",
        }
        return m

    monkeypatch.setattr(playground_route, "GenerationPromptSettingsService", _fake_gs)
    monkeypatch.setattr(playground_route, "_build_full_prompt_for_playground", lambda _db, _cfg: "Prompt body")
    pc = playground_route.PlaygroundPromptConfig(
        model="gemini-2.5-flash-image",
        sections=[
            playground_route.PlaygroundSection(id="1", label="Scene", content="x", enabled=True, order=0),
        ],
    )
    monkeypatch.setattr(playground_route, "trend_to_playground_config", lambda *a, **k: pc)
    monkeypatch.setattr(playground_route.ImageProviderFactory, "create_from_settings", lambda *_a, **_k: object())

    if error is not None:
        def _raise(*_a, **_k):
            raise error
        monkeypatch.setattr(playground_route, "generate_with_retry", _raise)
    else:
        monkeypatch.setattr(
            playground_route,
            "generate_with_retry",
            lambda *_a, **_k: result
            or ImageGenerationResponse(
                image_content=SAMPLE_PNG_BYTES,
                image_contents=[SAMPLE_PNG_BYTES],
                model="gemini-2.5-flash-image",
                provider="gemini",
            ),
        )

    return TestClient(app)


def test_playground_batch_test_requires_trend_ids(monkeypatch):
    app = FastAPI()
    app.include_router(playground_route.router)
    app.dependency_overrides[playground_route.get_current_user] = lambda: {"username": "tester"}
    app.dependency_overrides[playground_route.get_db] = lambda: MagicMock()
    monkeypatch.setattr(playground_route, "_ensure_playground_schema", lambda _db: None)
    client = TestClient(app)
    resp = client.post(
        "/admin/playground/batch-test",
        files=[("images", ("a.jpg", b"x", "image/jpeg"))],
    )
    assert resp.status_code == 400


def test_playground_batch_test_streams_sse_and_done(monkeypatch):
    client = _batch_test_client(
        monkeypatch,
        result=ImageGenerationResponse(
            image_content=SAMPLE_PNG_BYTES,
            image_contents=[SAMPLE_PNG_BYTES],
            model="gemini-2.5-flash-image",
            provider="gemini",
        ),
    )
    resp = client.post(
        "/admin/playground/batch-test",
        files=[
            ("trend_ids", (None, json.dumps(["trend-1"]))),
            ("config_overlay", (None, "{}")),
            ("concurrency", (None, "2")),
            ("images", ("a.jpg", b"x", "image/jpeg")),
        ],
    )
    assert resp.status_code == 200
    text = resp.text
    assert "data:" in text
    assert '"done": true' in text or '"done":true' in text.replace(" ", "")
    assert "trend-1" in text


def test_playground_batch_test_partial_generation_error_still_streams(monkeypatch):
    client = _batch_test_client(monkeypatch, error=ImageGenerationError("forced"))
    resp = client.post(
        "/admin/playground/batch-test",
        files=[
            ("trend_ids", (None, json.dumps(["trend-1"]))),
            ("config_overlay", (None, "{}")),
            ("images", ("a.jpg", b"x", "image/jpeg")),
        ],
    )
    assert resp.status_code == 200
    assert '"status": "error"' in resp.text or '"status":"error"' in resp.text.replace(" ", "")
    assert '"done": true' in resp.text or '"done":true' in resp.text.replace(" ", "")


def test_playground_multi_test_requires_prompts(monkeypatch):
    app = FastAPI()
    app.include_router(playground_route.router)
    app.dependency_overrides[playground_route.get_current_user] = lambda: {"username": "tester"}
    app.dependency_overrides[playground_route.get_db] = lambda: MagicMock()
    monkeypatch.setattr(playground_route, "_ensure_playground_schema", lambda _db: None)
    client = TestClient(app)
    resp = client.post(
        "/admin/playground/multi-test",
        files=[
            ("config_base", (None, json.dumps(_config("gemini-2.5-flash-image")))),
            ("images", ("a.jpg", b"x", "image/jpeg")),
        ],
    )
    assert resp.status_code == 400


def test_playground_multi_test_rejects_too_many_prompts(monkeypatch):
    client = _make_client(
        monkeypatch,
        result=ImageGenerationResponse(
            image_content=SAMPLE_PNG_BYTES,
            image_contents=[SAMPLE_PNG_BYTES],
            model="gemini-2.5-flash-image",
            provider="gemini",
        ),
    )
    prompts = [f"p{i}" for i in range(6)]
    resp = client.post(
        "/admin/playground/multi-test",
        files=[
            ("prompts", (None, json.dumps(prompts))),
            ("config_base", (None, json.dumps(_config("gemini-2.5-flash-image")))),
            ("images", ("a.jpg", b"x", "image/jpeg")),
        ],
    )
    assert resp.status_code == 400
    assert "Too many prompts" in (resp.json().get("detail") or "")


def test_playground_multi_test_streams_sse_and_done(monkeypatch):
    client = _make_client(
        monkeypatch,
        result=ImageGenerationResponse(
            image_content=SAMPLE_PNG_BYTES,
            image_contents=[SAMPLE_PNG_BYTES],
            model="gemini-2.5-flash-image",
            provider="gemini",
        ),
    )
    resp = client.post(
        "/admin/playground/multi-test",
        files=[
            ("prompts", (None, json.dumps(["prompt one", "prompt two"]))),
            ("config_base", (None, json.dumps(_config("gemini-2.5-flash-image")))),
            ("concurrency", (None, "2")),
            ("images", ("a.jpg", b"x", "image/jpeg")),
        ],
    )
    assert resp.status_code == 200
    text = resp.text
    assert "data:" in text
    assert "variant_0" in text
    assert '"done": true' in text or '"done":true' in text.replace(" ", "")
