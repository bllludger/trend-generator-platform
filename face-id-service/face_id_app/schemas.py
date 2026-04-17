from typing import Any

from pydantic import BaseModel, Field


class ProcessRequest(BaseModel):
    asset_id: str
    source_path: str
    flow: str = "trend"
    user_id: str
    chat_id: str | None = None
    request_id: str
    callback_url: str
    callback_secret_id: str | None = "v1"
    detector_config: dict[str, Any] = Field(default_factory=dict)


class ProcessResponse(BaseModel):
    asset_id: str
    status: str = "queued"
