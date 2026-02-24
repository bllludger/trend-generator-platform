import os
import re
from typing import Any

import yaml

from app.core.config import settings
from app.schemas.prompts import PromptConfig


class PromptService:
    def __init__(self) -> None:
        self.base_path = settings.prompts_base_path

    def load(self, name: str) -> PromptConfig:
        payload = self._read_yaml(self._general_path(name))
        return PromptConfig(**payload)

    def update(self, name: str, payload: dict[str, Any]) -> PromptConfig:
        payload = {**payload, "name": name}
        config = PromptConfig(**payload)
        self._write_yaml(self._general_path(name), config.model_dump(exclude_none=True))
        return config

    def load_trend(self, trend_id: str) -> PromptConfig:
        path = self._find_trend_path(trend_id)
        if not path:
            raise FileNotFoundError(trend_id)
        payload = self._read_yaml(path)
        payload["trend_id"] = trend_id
        return PromptConfig(**payload)

    def update_trend(self, trend_id: str, payload: dict[str, Any]) -> PromptConfig:
        slug = payload.get("name") or self._slugify(payload.get("display_name") or "")
        if not slug:
            slug = f"trend_{trend_id[:8]}"
        payload = {**payload, "name": slug, "trend_id": trend_id}
        config = PromptConfig(**payload)
        self._delete_trend_files(trend_id)
        self._write_yaml(self._trend_path(trend_id, slug), config.model_dump(exclude_none=True))
        return config

    def list_general(self) -> list[PromptConfig]:
        configs: list[PromptConfig] = []
        for filename in self._list_yaml(self.base_path):
            name = filename.replace(".yaml", "")
            configs.append(self.load(name))
        return configs

    def list_trends(self) -> list[PromptConfig]:
        configs: list[PromptConfig] = []
        trend_dir = os.path.join(self.base_path, "trends")
        for filename in self._list_yaml(trend_dir):
            path = os.path.join(trend_dir, filename)
            payload = self._read_yaml(path)
            trend_id = payload.get("trend_id") or self._trend_id_from_filename(filename)
            if not trend_id:
                continue
            payload["trend_id"] = trend_id
            configs.append(PromptConfig(**payload))
        return configs

    def _general_path(self, name: str) -> str:
        return os.path.join(self.base_path, f"{name}.yaml")

    def _trend_path(self, trend_id: str, slug: str | None = None) -> str:
        if slug:
            return os.path.join(self.base_path, "trends", f"{slug}__{trend_id}.yaml")
        return os.path.join(self.base_path, "trends", f"{trend_id}.yaml")

    def _find_trend_path(self, trend_id: str) -> str | None:
        direct = self._trend_path(trend_id)
        if os.path.exists(direct):
            return direct
        trend_dir = os.path.join(self.base_path, "trends")
        if not os.path.exists(trend_dir):
            return None
        for filename in self._list_yaml(trend_dir):
            if filename.endswith(f"__{trend_id}.yaml"):
                return os.path.join(trend_dir, filename)
        return None

    def _list_yaml(self, path: str) -> list[str]:
        if not os.path.exists(path):
            return []
        return [f for f in os.listdir(path) if f.endswith(".yaml")]

    def _slugify(self, value: str) -> str:
        value = value.strip().lower()
        value = re.sub(r"[^a-z0-9]+", "_", value)
        return re.sub(r"_+", "_", value).strip("_")

    def _trend_id_from_filename(self, filename: str) -> str | None:
        base = filename.replace(".yaml", "")
        if "__" in base:
            return base.split("__", 1)[1]
        if self._looks_like_uuid(base):
            return base
        return None

    def _looks_like_uuid(self, value: str) -> bool:
        return bool(re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value))

    def _delete_trend_files(self, trend_id: str) -> None:
        trend_dir = os.path.join(self.base_path, "trends")
        if not os.path.exists(trend_dir):
            return
        for filename in self._list_yaml(trend_dir):
            if filename == f"{trend_id}.yaml" or filename.endswith(f"__{trend_id}.yaml"):
                try:
                    os.remove(os.path.join(trend_dir, filename))
                except OSError:
                    continue

    def _read_yaml(self, path: str) -> dict[str, Any]:
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data

    def _write_yaml(self, path: str, payload: dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)
