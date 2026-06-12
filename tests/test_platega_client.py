from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from app.services.platega import PlategaClient, PlategaConfig


class FakeResponse:
    def __init__(self, status_code: int, json_data: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text
        self.request = httpx.Request("POST", "https://app.platega.io")

    def json(self) -> dict:
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            response = httpx.Response(
                self.status_code,
                request=self.request,
                text=self.text,
            )
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=self.request,
                response=response,
            )


class FakeHttpClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict]] = []

    async def post(self, url: str, *, headers: dict, json: dict) -> FakeResponse:
        self.calls.append(("POST", url, json))
        return self.responses.pop(0)

    async def get(self, url: str, *, headers: dict) -> FakeResponse:
        self.calls.append(("GET", url, {}))
        return self.responses.pop(0)


class FakeHttpClientContext:
    def __init__(self, client: FakeHttpClient) -> None:
        self.client = client

    async def __aenter__(self) -> FakeHttpClient:
        return self.client

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


def _client(*, base_url: str = "https://app.platega.io", api_version: str = "v1") -> PlategaClient:
    return PlategaClient(
        PlategaConfig(
            base_url=base_url,
            merchant_id="merchant",
            secret="secret",
            return_url="https://example.com/success",
            failed_url="https://example.com/fail",
            api_version=api_version,
        )
    )


class PlategaClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_v2_response_url_is_available_as_redirect(self) -> None:
        fake = FakeHttpClient(
            [
                FakeResponse(
                    200,
                    {
                        "transactionId": "tx-1",
                        "url": "https://pay.platega.io/?id=tx-1",
                        "status": "PENDING",
                    },
                )
            ]
        )

        with patch(
            "app.services.platega.external_httpx_client",
            lambda **kwargs: FakeHttpClientContext(fake),
        ):
            data = await _client(api_version="v2").create_payment_link(
                amount=500,
                currency="RUB",
                description="Credits",
                payload={"tgUserId": 1},
                payment_method=2,
        )

        self.assertEqual(fake.calls[0][1], "https://app.platega.io/v2/transaction/process")
        self.assertNotIn("paymentMethod", fake.calls[0][2])
        self.assertEqual(data["redirect"], "https://pay.platega.io/?id=tx-1")

    async def test_v1_card_create_400_retries_v2_endpoint(self) -> None:
        fake = FakeHttpClient(
            [
                FakeResponse(400, text="No available card cascades"),
                FakeResponse(
                    200,
                    {
                        "transactionId": "tx-2",
                        "url": "https://pay.platega.io/?id=tx-2",
                        "status": "PENDING",
                    },
                ),
            ]
        )

        with patch(
            "app.services.platega.external_httpx_client",
            lambda **kwargs: FakeHttpClientContext(fake),
        ):
            data = await _client(api_version="v1").create_payment_link(
                amount=500,
                currency="RUB",
                description="Credits",
                payload={"tgUserId": 1},
                payment_method=11,
            )

        self.assertEqual(
            [call[1] for call in fake.calls],
            [
                "https://app.platega.io/transaction/process",
                "https://app.platega.io/v2/transaction/process",
            ],
        )
        self.assertEqual(fake.calls[0][2]["paymentMethod"], 11)
        self.assertNotIn("paymentMethod", fake.calls[1][2])
        self.assertEqual(data["redirect"], "https://pay.platega.io/?id=tx-2")

    async def test_status_check_uses_root_transaction_path_for_v2_base_url(self) -> None:
        fake = FakeHttpClient([FakeResponse(200, {"status": "CONFIRMED"})])

        with patch(
            "app.services.platega.external_httpx_client",
            lambda **kwargs: FakeHttpClientContext(fake),
        ):
            status = await _client(
                base_url="https://app.platega.io/v2",
                api_version="v2",
            ).get_transaction_status("tx-3")

        self.assertEqual(status, "CONFIRMED")
        self.assertEqual(fake.calls[0][1], "https://app.platega.io/transaction/tx-3")


if __name__ == "__main__":
    unittest.main()
