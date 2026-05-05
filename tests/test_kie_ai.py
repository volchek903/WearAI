from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import httpx

from app.services.kie_ai import WaveSpeedClient, WaveSpeedError
from app.utils.kie_errors import kie_error_to_user_text


class _CreateReadErrorClient:
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs

    async def __aenter__(self) -> _CreateReadErrorClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        del exc_type, exc, tb
        return False

    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        del kwargs
        raise httpx.ReadError(
            "upstream closed",
            request=httpx.Request(method, url),
        )


class _RetryUploadClient:
    calls = 0

    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs

    async def __aenter__(self) -> _RetryUploadClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        del exc_type, exc, tb
        return False

    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        del kwargs
        type(self).calls += 1
        request = httpx.Request(method, url)
        if type(self).calls == 1:
            raise httpx.ReadError("temporary failure", request=request)
        return httpx.Response(
            200,
            json={
                "code": 200,
                "data": {"download_url": "https://example.com/uploaded.png"},
            },
            request=request,
        )


class WaveSpeedClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_task_wraps_transport_errors(self) -> None:
        client = WaveSpeedClient(api_key="test-key")

        with patch("app.services.kie_ai.httpx.AsyncClient", _CreateReadErrorClient):
            with self.assertRaises(WaveSpeedError) as ctx:
                await client.create_nano_banana_pro_edit_task(
                    prompt="make it cinematic",
                    image_input_urls=["https://example.com/input.png"],
                )

        self.assertIn("WaveSpeed create task failed", str(ctx.exception))
        self.assertIn("ReadError", str(ctx.exception))

    async def test_upload_retries_transient_read_error(self) -> None:
        client = WaveSpeedClient(api_key="test-key")
        _RetryUploadClient.calls = 0

        with patch("app.services.kie_ai.httpx.AsyncClient", _RetryUploadClient):
            with patch("app.services.kie_ai.asyncio.sleep", new=AsyncMock()) as sleep_mock:
                url = await client.upload_image_bytes(
                    data=b"image-bytes",
                    filename="source.png",
                )

        self.assertEqual(url, "https://example.com/uploaded.png")
        self.assertEqual(_RetryUploadClient.calls, 2)
        sleep_mock.assert_awaited_once()


class KieErrorTextTests(unittest.TestCase):
    def test_transport_failures_map_to_network_message(self) -> None:
        text = kie_error_to_user_text(
            WaveSpeedError("WaveSpeed create task failed: ReadError: upstream closed")
        )
        self.assertIn("Проблема на стороне сети", text)


if __name__ == "__main__":
    unittest.main()
