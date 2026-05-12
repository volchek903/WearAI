from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.services.wavespeed_ai import WaveSpeedError, get_wavespeed_api_key_from_env
from app.utils.http_client import external_httpx_client

logger = logging.getLogger(__name__)

_SUCCESS_STATES = {"completed", "succeeded", "success", "done", "finished"}
_FAILED_STATES = {
    "failed",
    "error",
    "errored",
    "canceled",
    "cancelled",
    "rejected",
    "terminated",
    "aborted",
    "timeout",
}
_RETRYABLE_HTTP_GET_ERRORS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
)


def _format_transport_error(exc: Exception | None) -> str:
    if exc is None:
        return "unknown transport error"
    text = str(exc).strip()
    if not text:
        return exc.__class__.__name__
    return f"{exc.__class__.__name__}: {text}"


class WaveSpeedAceStepClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        api_base: str = "https://api.wavespeed.ai",
        timeout_s: float = 60.0,
    ) -> None:
        self.api_key = api_key or get_wavespeed_api_key_from_env()
        if not self.api_key:
            raise WaveSpeedError("WAVESPEED_API_KEY is empty.")
        self.api_base = api_base.rstrip("/")
        self.timeout = httpx.Timeout(timeout_s)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    @staticmethod
    def _extract_task_id(payload: dict[str, Any]) -> str | None:
        data = payload.get("data") or {}
        task_id = data.get("id") or data.get("taskId")
        return str(task_id) if task_id else None

    @staticmethod
    def _extract_status(payload: dict[str, Any]) -> str:
        data = payload.get("data") or {}
        raw = (
            data.get("status")
            or data.get("state")
            or data.get("phase")
            or data.get("task_status")
            or ""
        )
        return str(raw).strip().lower()

    @staticmethod
    def _extract_outputs(payload: dict[str, Any]) -> list[str]:
        data = payload.get("data") or {}
        outputs = data.get("outputs") or []
        out: list[str] = []
        if not isinstance(outputs, list):
            return out
        for item in outputs:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
                continue
            if isinstance(item, dict):
                for key in ("audio", "url", "download_url", "downloadUrl", "href", "output"):
                    value = item.get(key)
                    if isinstance(value, str) and value.strip():
                        out.append(value.strip())
                        break
        return out

    async def create_ace_step_task(
        self,
        *,
        tags: str,
        lyrics: str,
        duration: int,
        seed: int = -1,
    ) -> str:
        body = {
            "tags": tags,
            "lyrics": lyrics,
            "duration": int(duration),
            "seed": int(seed),
        }
        url = f"{self.api_base}/api/v3/wavespeed-ai/ace-step-1.5"

        logger.info("wavespeed ace-step create: duration=%s tags=%s", duration, tags)
        async with external_httpx_client(timeout=self.timeout) as client:
            resp = await client.post(
                url,
                headers={**self._headers(), "Content-Type": "application/json"},
                json=body,
            )
            if resp.status_code != 200:
                raise WaveSpeedError(
                    f"WaveSpeed ACE-Step create failed [HTTP {resp.status_code}]: {resp.text}"
                )

            payload = resp.json()
            if int(payload.get("code", 0)) != 200:
                raise WaveSpeedError(f"WaveSpeed ACE-Step create failed: {payload}")

            task_id = self._extract_task_id(payload)
            if not task_id:
                raise WaveSpeedError(f"WaveSpeed ACE-Step response has no id: {payload}")
            return task_id

    async def get_task_result(self, task_id: str) -> dict[str, Any]:
        url = f"{self.api_base}/api/v3/predictions/{task_id}/result"
        max_attempts = 5
        last_exc: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                async with external_httpx_client(timeout=self.timeout) as client:
                    resp = await client.get(url, headers=self._headers())
                if resp.status_code != 200:
                    raise WaveSpeedError(
                        f"WaveSpeed ACE-Step result failed [HTTP {resp.status_code}]: {resp.text}"
                    )
                payload = resp.json()
                if int(payload.get("code", 0)) != 200:
                    raise WaveSpeedError(f"WaveSpeed ACE-Step result failed: {payload}")
                return payload
            except _RETRYABLE_HTTP_GET_ERRORS as e:
                last_exc = e
                if attempt >= max_attempts:
                    break
                backoff = min(10.0, 1.5 * attempt)
                logger.warning(
                    "wavespeed ace-step: transient get_task_result error task_id=%s "
                    "attempt=%s/%s error=%s retry_in=%.1fs",
                    task_id,
                    attempt,
                    max_attempts,
                    e.__class__.__name__,
                    backoff,
                )
                await asyncio.sleep(backoff)

        raise WaveSpeedError(
            "WaveSpeed ACE-Step result failed after "
            f"{max_attempts} attempts: {_format_transport_error(last_exc)}"
        )

    async def wait_audio_url(
        self,
        task_id: str,
        *,
        max_wait_s: int = 30 * 60,
        poll_interval_s: int = 5,
    ) -> str:
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        deadline = started_at + max_wait_s
        last_state = ""

        while loop.time() < deadline:
            payload = await self.get_task_result(task_id)
            state = self._extract_status(payload)
            if state and state != last_state:
                logger.info("wavespeed ace-step: task_id=%s status=%s", task_id, state)
                last_state = state

            if state in _SUCCESS_STATES:
                outputs = self._extract_outputs(payload)
                if not outputs:
                    raise WaveSpeedError(f"No outputs in WaveSpeed ACE-Step result: {payload}")
                return outputs[0]

            if state in _FAILED_STATES:
                data = payload.get("data") or {}
                fail_msg = data.get("error") or payload.get("message") or "WaveSpeed task failed"
                raise WaveSpeedError(str(fail_msg))

            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(float(poll_interval_s), remaining))

        raise WaveSpeedError(f"ACE-Step timeout after {max_wait_s}s (taskId={task_id})")

    async def download_audio_bytes(self, url: str) -> tuple[str, bytes]:
        last_exc: Exception | None = None
        max_attempts = 8

        for attempt in range(1, max_attempts + 1):
            try:
                async with external_httpx_client(timeout=httpx.Timeout(180.0)) as client:
                    resp = await client.get(url, headers=self._headers())
                    if resp.status_code >= 400:
                        resp = await client.get(url)
                if resp.status_code >= 400:
                    raise WaveSpeedError(
                        f"ACE-Step audio download failed [HTTP {resp.status_code}]"
                    )
                filename = Path(urlparse(str(resp.url)).path).name or "ace-step-output.mp3"
                return filename, resp.content
            except _RETRYABLE_HTTP_GET_ERRORS as e:
                last_exc = e
                if attempt >= max_attempts:
                    break
                backoff = min(15.0, 2.0 * attempt)
                logger.warning(
                    "wavespeed ace-step: transient download error attempt=%s/%s "
                    "error=%s retry_in=%.1fs url=%s",
                    attempt,
                    max_attempts,
                    e.__class__.__name__,
                    backoff,
                    url,
                )
                await asyncio.sleep(backoff)

        raise WaveSpeedError(
            f"ACE-Step audio download failed: {_format_transport_error(last_exc)}"
        )
