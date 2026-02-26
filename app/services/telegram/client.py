"""
Telegram client wrapper using httpx sync client.
Provides sync interface for Celery workers (no event loop issues).
"""
import json
import time
import logging

import httpx

from app.core.config import settings
from app.services.telegram_messages.runtime import runtime_templates
from app.utils.metrics import (
    telegram_requests_total,
    telegram_request_duration_seconds,
)


logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramClient:
    """
    Sync Telegram client for Celery workers.
    Uses httpx sync client - no event loop issues.
    """

    def __init__(self) -> None:
        self._token = settings.telegram_bot_token
        self._base_url = f"{TELEGRAM_API_BASE}/bot{self._token}"
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        """Lazy initialization of httpx client."""
        if self._client is None:
            self._client = httpx.Client(timeout=30.0)
        return self._client

    def _record_request(self, method: str, status: str, duration: float) -> None:
        telegram_requests_total.labels(method=method, status=status).inc()
        telegram_request_duration_seconds.labels(method=method).observe(duration)

    def _api_call(self, method: str, data: dict | None = None, files: dict | None = None) -> dict:
        """Make API call to Telegram."""
        url = f"{self._base_url}/{method}"
        if files:
            resp = self.client.post(url, data=data, files=files)
        else:
            resp = self.client.post(url, json=data)
        result = resp.json()
        if not result.get("ok"):
            error_desc = result.get("description", "Unknown error")
            error_code = result.get("error_code", 0)
            logger.warning(f"Telegram API error: {method} -> {error_code}: {error_desc}")
            raise Exception(f"{error_code}: {error_desc}")
        return result

    def send_message(
        self,
        chat_id: str,
        text: str,
        reply_markup: dict | None = None,
        parse_mode: str | None = None,
    ) -> dict:
        """Send text message to chat."""
        start = time.time()
        try:
            data = {"chat_id": int(chat_id), "text": runtime_templates.resolve_literal(text)}
            if reply_markup:
                data["reply_markup"] = reply_markup
            if parse_mode:
                data["parse_mode"] = parse_mode
            result = self._api_call("sendMessage", data)
            self._record_request("sendMessage", "success", time.time() - start)
            return result
        except Exception as e:
            self._record_request("sendMessage", "error", time.time() - start)
            logger.error("Failed to send message", extra={"error": str(e), "chat_id": chat_id})
            raise

    def edit_message(self, chat_id: str, message_id: int, text: str) -> None:
        """Edit message text (for progress updates)."""
        start = time.time()
        try:
            data = {
                "chat_id": int(chat_id),
                "message_id": int(message_id),
                "text": runtime_templates.resolve_literal(text),
            }
            logger.info(f"editMessageText: chat={chat_id}, msg_id={message_id}, text_len={len(text)}")
            self._api_call("editMessageText", data)
            self._record_request("editMessageText", "success", time.time() - start)
        except Exception as e:
            self._record_request("editMessageText", "error", time.time() - start)
            logger.warning(f"Failed to edit message: {e} | chat={chat_id}, msg_id={message_id}")

    def delete_message(self, chat_id: str, message_id: int) -> None:
        """Delete message (e.g. progress bar after sending result)."""
        start = time.time()
        try:
            data = {"chat_id": int(chat_id), "message_id": message_id}
            self._api_call("deleteMessage", data)
            self._record_request("deleteMessage", "success", time.time() - start)
        except Exception as e:
            self._record_request("deleteMessage", "error", time.time() - start)
            logger.warning("Failed to delete message", extra={"error": str(e), "chat_id": chat_id})

    def send_chat_action(self, chat_id: str, action: str = "typing") -> None:
        """Send chat action indicator (typing/upload_photo/etc.)."""
        start = time.time()
        try:
            data = {"chat_id": int(chat_id), "action": action}
            self._api_call("sendChatAction", data)
            self._record_request("sendChatAction", "success", time.time() - start)
        except Exception as e:
            self._record_request("sendChatAction", "error", time.time() - start)
            logger.warning("Failed to send chat action", extra={"error": str(e), "chat_id": chat_id, "action": action})

    def send_photo(
        self,
        chat_id: str,
        photo_path: str,
        caption: str | None = None,
        reply_markup: dict | None = None,
    ) -> None:
        """Send photo to chat. reply_markup — inline-клавиатура (например, «Что дальше?»)."""
        start = time.time()
        try:
            with open(photo_path, "rb") as f:
                files = {"photo": (photo_path.split("/")[-1], f, "image/png")}
                data = {"chat_id": int(chat_id)}
                if caption:
                    data["caption"] = runtime_templates.resolve_literal(caption)
                if reply_markup:
                    # В multipart/form-data reply_markup передаётся как JSON-строка
                    data["reply_markup"] = json.dumps(reply_markup)
                self._api_call("sendPhoto", data=data, files=files)
            self._record_request("sendPhoto", "success", time.time() - start)
        except Exception as e:
            self._record_request("sendPhoto", "error", time.time() - start)
            logger.error("Failed to send photo", extra={"error": str(e), "chat_id": chat_id})
            raise

    def send_media_group(
        self,
        chat_id: str,
        media: list[dict],
    ) -> dict:
        """Send media group (album) to chat. Each item: {type, media_path, caption?}."""
        start = time.time()
        try:
            input_media = []
            files = {}
            for i, item in enumerate(media):
                attach_key = f"photo_{i}"
                input_media.append({
                    "type": item.get("type", "photo"),
                    "media": f"attach://{attach_key}",
                    "caption": item.get("caption", ""),
                })
                f = open(item["media_path"], "rb")
                files[attach_key] = (item["media_path"].split("/")[-1], f, "image/png")
            data = {
                "chat_id": str(int(chat_id)),
                "media": json.dumps(input_media),
            }
            result = self._api_call("sendMediaGroup", data=data, files=files)
            self._record_request("sendMediaGroup", "success", time.time() - start)
            for key in files:
                try:
                    files[key][1].close()
                except Exception:
                    pass
            return result
        except Exception as e:
            self._record_request("sendMediaGroup", "error", time.time() - start)
            logger.error("Failed to send media group", extra={"error": str(e), "chat_id": chat_id})
            raise

    def send_document(
        self,
        chat_id: str,
        document_path: str,
        caption: str | None = None,
        reply_markup: dict | None = None,
    ) -> None:
        """Send document to chat (original file, no compression)."""
        start = time.time()
        try:
            filename = document_path.split("/")[-1]
            mime_type = "application/octet-stream"
            lower = filename.lower()
            if lower.endswith(".png"):
                mime_type = "image/png"
            elif lower.endswith(".jpg") or lower.endswith(".jpeg"):
                mime_type = "image/jpeg"
            elif lower.endswith(".webp"):
                mime_type = "image/webp"
            with open(document_path, "rb") as f:
                files = {"document": (filename, f, mime_type)}
                data = {"chat_id": int(chat_id)}
                if caption:
                    data["caption"] = runtime_templates.resolve_literal(caption)
                if reply_markup:
                    data["reply_markup"] = json.dumps(reply_markup)
                self._api_call("sendDocument", data=data, files=files)
            self._record_request("sendDocument", "success", time.time() - start)
        except Exception as e:
            self._record_request("sendDocument", "error", time.time() - start)
            logger.error("Failed to send document", extra={"error": str(e), "chat_id": chat_id})
            raise

    def close(self) -> None:
        """Close httpx client."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception as e:
                logger.warning("Failed to close client", extra={"error": str(e)})
            finally:
                self._client = None
