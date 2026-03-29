"""
Клиент ЮKassa API: создание платежа с redirect (Умный платёж).
Idempotence-Key уникален на одну попытку (при ретрае — тот же ключ; новая попытка — новый ключ).
"""
import base64
import logging
from typing import Any

import httpx

from app.core.config import settings
from app.paywall.config import get_unlock_amount_yookassa_value

logger = logging.getLogger(__name__)

YOOKASSA_API_BASE = "https://api.yookassa.ru/v3"


class YooKassaClientError(Exception):
    """Ошибка вызова API ЮKassa."""
    def __init__(self, message: str, status_code: int | None = None, response_body: str | None = None):
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(message)


def _basic_auth(shop_id: str, secret_key: str) -> str:
    raw = f"{shop_id}:{secret_key}"
    return base64.b64encode(raw.encode()).decode()


class YooKassaClient:
    """Синхронный клиент для создания платежа ЮKassa (redirect)."""

    def __init__(
        self,
        shop_id: str | None = None,
        secret_key: str | None = None,
    ):
        self.shop_id = shop_id or (getattr(settings, "yookassa_shop_id", "") or "")
        self.secret_key = secret_key or (getattr(settings, "yookassa_secret_key", "") or "")
        self._auth = _basic_auth(self.shop_id, self.secret_key) if (self.shop_id and self.secret_key) else None

    def is_configured(self) -> bool:
        return bool(self.shop_id and self.secret_key)

    def create_payment(
        self,
        order_id: str,
        return_url: str,
        idempotence_key: str,
        amount_value: str | None = None,
        description: str = "Разблокировка фото",
    ) -> dict[str, Any]:
        """
        Создать платёж с confirmation type redirect.
        :param order_id: идентификатор unlock_order (в metadata и для return_url).
        :param return_url: URL возврата после оплаты (должен содержать order_id, например t.me/bot?start=unlock_done_<order_id>).
        :param idempotence_key: уникальный ключ попытки (UUID или order:order_id:attempt:attempt_id). При ретрае — тот же ключ.
        :param amount_value: сумма в рублях строкой, например "99.00". По умолчанию из get_unlock_amount_yookassa_value().
        :param description: описание платежа.
        :return: dict с id, confirmation.confirmation_url, status и т.д. Или raise YooKassaClientError.
        """
        if not self._auth:
            raise YooKassaClientError("YooKassa не настроен: задайте YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY")

        value = amount_value or get_unlock_amount_yookassa_value()
        payload = {
            "amount": {"value": value, "currency": "RUB"},
            "capture": True,
            "confirmation": {"type": "redirect", "return_url": return_url},
            "description": description,
            "metadata": {"order_id": order_id},
        }

        url = f"{YOOKASSA_API_BASE}/payments"
        headers = {
            "Authorization": f"Basic {self._auth}",
            "Idempotence-Key": idempotence_key,
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(url, json=payload, headers=headers)
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
            logger.warning(
                "yookassa_create_payment_network_error",
                extra={"order_id": order_id, "error": str(exc)},
            )
            raise YooKassaClientError(
                f"Network error: {exc}",
                status_code=None,
                response_body=None,
            ) from exc

        body = resp.text
        try:
            data = resp.json()
        except Exception:
            data = {}

        if resp.status_code >= 400:
            logger.warning(
                "yookassa_create_payment_error",
                extra={"status": resp.status_code, "order_id": order_id, "body": body[:500]},
            )
            raise YooKassaClientError(
                data.get("description", body) or f"HTTP {resp.status_code}",
                status_code=resp.status_code,
                response_body=body,
            )

        return data

    def get_payment(self, payment_id: str) -> dict[str, Any] | None:
        """
        GET /v3/payments/{payment_id} — второй контур подтверждения оплаты.
        Returns payment object or None on error.
        """
        if not self._auth:
            return None
        url = f"{YOOKASSA_API_BASE}/payments/{payment_id}"
        headers = {"Authorization": f"Basic {self._auth}"}
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(url, headers=headers)
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
            logger.warning("yookassa_get_payment_network_error", extra={"payment_id": payment_id, "error": str(exc)})
            return None
        if resp.status_code != 200:
            logger.warning("yookassa_get_payment_error", extra={"payment_id": payment_id, "status": resp.status_code})
            return None
        return resp.json()
