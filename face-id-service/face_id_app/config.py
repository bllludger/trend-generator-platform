import json

from pydantic_settings import BaseSettings, SettingsConfigDict


class FaceIdConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    redis_password: str = "redis"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None

    face_id_callback_secret: str = "face-id-dev-secret"
    face_id_callback_secrets_json: str = ""
    callback_timeout_seconds: float = 2.0
    callback_max_retries: int = 3
    callback_backoff_seconds: float = 1.0

    storage_base_path: str = "/data/generated_images"
    output_subdir: str = "face_id"
    max_image_pixels: int = 40_000_000
    callback_allowed_hosts: str = "api,localhost,127.0.0.1"
    face_detector_short_model_url: str = (
        "https://storage.googleapis.com/mediapipe-models/face_detector/"
        "blaze_face_short_range/float16/latest/blaze_face_short_range.tflite"
    )
    face_detector_full_model_url: str = (
        "https://storage.googleapis.com/mediapipe-models/face_detector/"
        "blaze_face_full_range/float16/latest/blaze_face_full_range.tflite"
    )
    face_detector_models_dir: str = "/tmp/mediapipe_models"
    api_port: int = 8010
    worker_metrics_port: int = 9094
    model_version: str = "mediapipe-face-detection-v1"

    def resolved_broker(self) -> str:
        if self.celery_broker_url:
            return self.celery_broker_url
        return f"redis://:{self.redis_password}@redis:6379/0"

    def resolved_backend(self) -> str:
        if self.celery_result_backend:
            return self.celery_result_backend
        return f"redis://:{self.redis_password}@redis:6379/0"

    def callback_allowed_hosts_set(self) -> set[str]:
        raw = str(self.callback_allowed_hosts or "")
        return {h.strip().lower() for h in raw.split(",") if h.strip()}

    def callback_secrets_map(self) -> dict[str, str]:
        raw = str(self.face_id_callback_secrets_json or "").strip()
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        out: dict[str, str] = {}
        for k, v in data.items():
            key = str(k or "").strip()
            val = str(v or "").strip()
            if key and val:
                out[key] = val
        return out

    def resolve_callback_secret(self, callback_secret_id: str | None) -> str:
        sid = str(callback_secret_id or "").strip()
        mapped = self.callback_secrets_map().get(sid)
        return mapped or self.face_id_callback_secret


settings = FaceIdConfig()
