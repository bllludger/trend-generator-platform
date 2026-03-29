from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.yookassa.client import YooKassaClient, YooKassaClientError


def test_create_payment_raises_client_error_on_network_timeout():
    client = YooKassaClient(shop_id="shop", secret_key="secret")
    mocked_http = MagicMock()
    mocked_http.__enter__.return_value = mocked_http
    mocked_http.post.side_effect = httpx.TimeoutException("timeout")

    with patch("app.services.yookassa.client.httpx.Client", return_value=mocked_http):
        with pytest.raises(YooKassaClientError) as exc:
            client.create_payment(
                order_id="ord-1",
                return_url="https://t.me/bot?start=unlock_done_ord-1",
                idempotence_key="idem-1",
            )

    assert "Network error" in str(exc.value)


def test_get_payment_returns_none_on_network_error():
    client = YooKassaClient(shop_id="shop", secret_key="secret")
    mocked_http = MagicMock()
    mocked_http.__enter__.return_value = mocked_http
    mocked_http.get.side_effect = httpx.ConnectError("connection", request=MagicMock())

    with patch("app.services.yookassa.client.httpx.Client", return_value=mocked_http):
        result = client.get_payment("pay-1")

    assert result is None
