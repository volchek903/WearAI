from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Sequence

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PhotoSettingsDTO:
    aspect_ratio: str = "9:16"
    resolution: str = "1K"  # 1K / 2K / 4K
    output_format: str = "png"  # png / jpg


DEFAULT_PHOTO_SETTINGS = PhotoSettingsDTO()

_ALLOWED_ASPECTS = {
    "1:1",
    "2:3",
    "3:2",
    "3:4",
    "4:3",
    "4:5",
    "5:4",
    "9:16",
    "16:9",
    "21:9",
    "1:4",
    "4:1",
    "1:8",
    "8:1",
}
_ALLOWED_RESOLUTIONS = {"1K", "2K", "4K"}
_ALLOWED_FORMATS = {"png", "jpg", "jpeg"}
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


def _norm_aspect_ratio(v: str) -> str:
    v = (v or "").strip()
    if v == "auto":
        return DEFAULT_PHOTO_SETTINGS.aspect_ratio
    return v if v in _ALLOWED_ASPECTS else DEFAULT_PHOTO_SETTINGS.aspect_ratio


def _norm_resolution(v: str) -> str:
    del v
    return "1K"


def _norm_output_format(v: str) -> str:
    v = (v or "").strip().lower()
    if v == "jpeg":
        v = "jpg"
    return v if v in _ALLOWED_FORMATS else DEFAULT_PHOTO_SETTINGS.output_format


def _to_wavespeed_resolution(v: str) -> str:
    r = _norm_resolution(v)
    return r.lower()


def _to_wavespeed_output(v: str) -> str:
    fmt = _norm_output_format(v)
    return "jpeg" if fmt == "jpg" else "png"


def _seedream_size_from_aspect_ratio(v: str) -> str:
    sizes = {
        "1:1": "2048*2048",
        "2:3": "1536*2304",
        "3:2": "2304*1536",
        "3:4": "1536*2048",
        "4:3": "2048*1536",
        "4:5": "1792*2240",
        "5:4": "2240*1792",
        "9:16": "1728*3072",
        "16:9": "3072*1728",
        "21:9": "3360*1440",
    }
    return sizes.get(_norm_aspect_ratio(v), "2048*2048")


async def _load_photo_settings_from_db(
    session: AsyncSession, tg_id: int
) -> PhotoSettingsDTO:
    from app.models.user import User
    from app.models.user_photo_settings import UserPhotoSettings

    res = await session.execute(select(User).where(User.tg_id == tg_id))
    user = res.scalar_one_or_none()
    if not user:
        return DEFAULT_PHOTO_SETTINGS

    res2 = await session.execute(
        select(UserPhotoSettings).where(UserPhotoSettings.user_id == user.id)
    )
    s = res2.scalar_one_or_none()
    if not s:
        return DEFAULT_PHOTO_SETTINGS

    return PhotoSettingsDTO(
        aspect_ratio=_norm_aspect_ratio(
            getattr(s, "aspect_ratio", DEFAULT_PHOTO_SETTINGS.aspect_ratio)
        ),
        resolution=_norm_resolution(
            getattr(s, "resolution", DEFAULT_PHOTO_SETTINGS.resolution)
        ),
        output_format=_norm_output_format(
            getattr(s, "output_format", DEFAULT_PHOTO_SETTINGS.output_format)
        ),
    )


class WaveSpeedError(RuntimeError):
    pass


def _debug_save_upload_image(data: bytes, filename: str) -> None:
    # User-uploaded source images must not be persisted locally.
    del data, filename
    return


class WaveSpeedClient:
    """
    Backward-compatible wrapper with the old class name,
    implemented via WaveSpeed API.
    """

    def __init__(
        self,
        api_key: str,
        *,
        api_base: str = "https://api.wavespeed.ai",
        upload_base: str = "https://api.wavespeed.ai",
        timeout_s: float = 60.0,
    ) -> None:
        if not api_key:
            raise WaveSpeedError(
                "WAVESPEED_API_KEY is empty. Put it into .env "
                "(fallback KIE_API_KEY is also supported)."
            )
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.upload_base = upload_base.rstrip("/")
        self.timeout = httpx.Timeout(timeout_s)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    @staticmethod
    def _extract_task_id(payload: dict[str, Any]) -> str | None:
        data = payload.get("data") or {}
        task_id = data.get("id") or data.get("taskId")
        if task_id:
            return str(task_id)
        return None

    @staticmethod
    def _extract_outputs(payload: dict[str, Any]) -> list[str]:
        data = payload.get("data") or {}
        outputs = data.get("outputs") or []
        if not isinstance(outputs, list):
            return []
        out: list[str] = []
        for item in outputs:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
                continue
            if isinstance(item, dict):
                for key in ("url", "download_url", "downloadUrl", "output", "href"):
                    v = item.get(key)
                    if isinstance(v, str) and v.strip():
                        out.append(v.strip())
                        break
        return out

    @staticmethod
    def _extract_status(data: dict[str, Any]) -> str:
        raw = (
            data.get("status")
            or data.get("state")
            or data.get("phase")
            or data.get("task_status")
            or ""
        )
        return str(raw).strip().lower()

    async def upload_image_bytes(
        self,
        *,
        data: bytes,
        filename: str,
        upload_path: str = "images/user-uploads",
    ) -> str:
        del upload_path
        url = f"{self.upload_base}/api/v3/media/upload/binary"

        _debug_save_upload_image(data, filename)

        files = {"file": (filename or "image.png", data, "application/octet-stream")}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, headers=self._headers(), files=files)
            if resp.status_code != 200:
                raise WaveSpeedError(
                    f"WaveSpeed upload failed [HTTP {resp.status_code}]: {resp.text}"
                )

            payload = resp.json()
            if int(payload.get("code", 0)) != 200:
                raise WaveSpeedError(f"WaveSpeed upload failed: {payload}")

            data_obj = payload.get("data") or {}
            download_url = data_obj.get("download_url") or data_obj.get("downloadUrl")
            if not download_url:
                raise WaveSpeedError(
                    f"WaveSpeed upload response has no download_url: {payload}"
                )

            return str(download_url)

    async def create_nano_banana_2_task(
        self,
        *,
        prompt: str,
        image_input_urls: Sequence[str],
        settings: PhotoSettingsDTO | None = None,
        session: AsyncSession | None = None,
        tg_id: int | None = None,
        callback_url: str | None = None,
    ) -> str:
        del callback_url

        if session is not None and tg_id is not None:
            try:
                settings = await _load_photo_settings_from_db(
                    session=session,
                    tg_id=tg_id,
                )
            except Exception:
                settings = settings or DEFAULT_PHOTO_SETTINGS

        if settings is None:
            settings = DEFAULT_PHOTO_SETTINGS

        body: dict[str, Any] = {
            "images": [str(u) for u in image_input_urls if isinstance(u, str) and u.strip()],
            "prompt": prompt,
            "aspect_ratio": _norm_aspect_ratio(settings.aspect_ratio),
            "resolution": "1k",
            "output_format": _to_wavespeed_output(settings.output_format),
            "enable_sync_mode": False,
            "enable_base64_output": False,
        }

        if not body["images"]:
            raise WaveSpeedError("WaveSpeed task requires at least one image URL")

        url = f"{self.api_base}/api/v3/google/nano-banana-2/edit"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                url,
                headers={**self._headers(), "Content-Type": "application/json"},
                json=body,
            )
            if resp.status_code != 200:
                raise WaveSpeedError(
                    f"WaveSpeed create task failed [HTTP {resp.status_code}]: {resp.text}"
                )

            payload = resp.json()
            if int(payload.get("code", 0)) != 200:
                raise WaveSpeedError(f"WaveSpeed create task failed: {payload}")

            task_id = self._extract_task_id(payload)
            if not task_id:
                raise WaveSpeedError(f"WaveSpeed create task response has no id: {payload}")

            return task_id

    async def create_nano_banana_pro_edit_task(
        self,
        *,
        prompt: str,
        image_input_urls: Sequence[str],
        settings: PhotoSettingsDTO | None = None,
        session: AsyncSession | None = None,
        tg_id: int | None = None,
        callback_url: str | None = None,
    ) -> str:
        del callback_url

        if session is not None and tg_id is not None:
            try:
                settings = await _load_photo_settings_from_db(
                    session=session,
                    tg_id=tg_id,
                )
            except Exception:
                settings = settings or DEFAULT_PHOTO_SETTINGS

        if settings is None:
            settings = DEFAULT_PHOTO_SETTINGS

        body: dict[str, Any] = {
            "images": [str(u) for u in image_input_urls if isinstance(u, str) and u.strip()],
            "prompt": prompt,
            "aspect_ratio": _norm_aspect_ratio(settings.aspect_ratio),
            "resolution": "1k",
            "output_format": _to_wavespeed_output(settings.output_format),
            "enable_sync_mode": False,
            "enable_base64_output": False,
        }

        if not body["images"]:
            raise WaveSpeedError("WaveSpeed task requires at least one image URL")

        url = f"{self.api_base}/api/v3/google/nano-banana-pro/edit"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                url,
                headers={**self._headers(), "Content-Type": "application/json"},
                json=body,
            )
            if resp.status_code != 200:
                raise WaveSpeedError(
                    f"WaveSpeed create task failed [HTTP {resp.status_code}]: {resp.text}"
                )

            payload = resp.json()
            if int(payload.get("code", 0)) != 200:
                raise WaveSpeedError(f"WaveSpeed create task failed: {payload}")

            task_id = self._extract_task_id(payload)
            if not task_id:
                raise WaveSpeedError(f"WaveSpeed create task response has no id: {payload}")

            return task_id

    async def create_seedream_v5_lite_task(
        self,
        *,
        prompt: str,
        reference_image_urls: Sequence[str] | None = None,
        size: str | None = None,
        output_format: str | None = None,
        settings: PhotoSettingsDTO | None = None,
        session: AsyncSession | None = None,
        tg_id: int | None = None,
        callback_url: str | None = None,
    ) -> str:
        del callback_url

        if session is not None and tg_id is not None:
            try:
                settings = await _load_photo_settings_from_db(
                    session=session,
                    tg_id=tg_id,
                )
            except Exception:
                settings = settings or DEFAULT_PHOTO_SETTINGS

        if settings is None:
            settings = DEFAULT_PHOTO_SETTINGS

        ref_urls = [
            str(url)
            for url in (reference_image_urls or [])
            if isinstance(url, str) and url.strip()
        ]
        body: dict[str, Any] = {
            "prompt": prompt,
            "enable_sync_mode": False,
            "enable_base64_output": False,
        }
        if size:
            body["size"] = str(size)
        elif not ref_urls:
            body["size"] = _seedream_size_from_aspect_ratio(settings.aspect_ratio)

        body["output_format"] = _to_wavespeed_output(output_format or settings.output_format)

        if ref_urls:
            body["images"] = ref_urls
            url = f"{self.api_base}/api/v3/bytedance/seedream-v5.0-lite/edit"
        else:
            url = f"{self.api_base}/api/v3/bytedance/seedream-v5.0-lite"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                url,
                headers={**self._headers(), "Content-Type": "application/json"},
                json=body,
            )
            if resp.status_code != 200:
                raise WaveSpeedError(
                    f"WaveSpeed create task failed [HTTP {resp.status_code}]: {resp.text}"
                )

            payload = resp.json()
            if int(payload.get("code", 0)) != 200:
                raise WaveSpeedError(f"WaveSpeed create task failed: {payload}")

            task_id = self._extract_task_id(payload)
            if not task_id:
                raise WaveSpeedError(f"WaveSpeed create task response has no id: {payload}")

            return task_id

    async def create_wan_27_text_to_image_task(
        self,
        *,
        prompt: str,
        size: str | None = None,
        width: int | None = None,
        height: int | None = None,
        thinking_mode: bool | None = None,
        seed: int | None = None,
        callback_url: str | None = None,
    ) -> str:
        del callback_url

        body: dict[str, Any] = {
            "prompt": prompt,
            "enable_sync_mode": False,
            "enable_base64_output": False,
        }
        if width is not None and height is not None:
            body["width"] = int(width)
            body["height"] = int(height)
        elif size:
            body["size"] = str(size)
        if thinking_mode is not None:
            body["thinking_mode"] = bool(thinking_mode)
        if seed is not None:
            body["seed"] = int(seed)

        url = f"{self.api_base}/api/v3/alibaba/wan-2.7/text-to-image"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                url,
                headers={**self._headers(), "Content-Type": "application/json"},
                json=body,
            )
            if resp.status_code != 200:
                raise WaveSpeedError(
                    f"WaveSpeed create task failed [HTTP {resp.status_code}]: {resp.text}"
                )

            payload = resp.json()
            if int(payload.get("code", 0)) != 200:
                raise WaveSpeedError(f"WaveSpeed create task failed: {payload}")

            task_id = self._extract_task_id(payload)
            if not task_id:
                raise WaveSpeedError(f"WaveSpeed create task response has no id: {payload}")

            return task_id

    async def create_seedream_v45_task(
        self,
        *,
        prompt: str,
        size: str | None = None,
        callback_url: str | None = None,
    ) -> str:
        del callback_url

        body: dict[str, Any] = {
            "prompt": prompt,
            "enable_sync_mode": False,
            "enable_base64_output": False,
        }
        if size:
            body["size"] = str(size)

        url = f"{self.api_base}/api/v3/bytedance/seedream-v4.5"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                url,
                headers={**self._headers(), "Content-Type": "application/json"},
                json=body,
            )
            if resp.status_code != 200:
                raise WaveSpeedError(
                    f"WaveSpeed create task failed [HTTP {resp.status_code}]: {resp.text}"
                )

            payload = resp.json()
            if int(payload.get("code", 0)) != 200:
                raise WaveSpeedError(f"WaveSpeed create task failed: {payload}")

            task_id = self._extract_task_id(payload)
            if not task_id:
                raise WaveSpeedError(f"WaveSpeed create task response has no id: {payload}")

            return task_id

    async def get_task(self, task_id: str) -> dict[str, Any]:
        url = f"{self.api_base}/api/v3/predictions/{task_id}/result"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, headers=self._headers())
            if resp.status_code != 200:
                raise WaveSpeedError(
                    f"WaveSpeed get result failed [HTTP {resp.status_code}]: {resp.text}"
                )

            payload = resp.json()
            if int(payload.get("code", 0)) != 200:
                raise WaveSpeedError(f"WaveSpeed get result failed: {payload}")

            return payload

    async def wait_result_urls(
        self,
        task_id: str,
        *,
        max_wait_s: int = 30 * 60,
    ) -> list[str]:
        elapsed = 0
        sleep_s = 2
        last_state = ""

        while elapsed < max_wait_s:
            payload = await self.get_task(task_id)
            data = payload.get("data") or {}
            state = self._extract_status(data)
            if state and state != last_state:
                logger.info(
                    "wavespeed: task_id=%s status=%s elapsed=%ss",
                    task_id,
                    state,
                    elapsed,
                )
                last_state = state

            if state in _SUCCESS_STATES:
                urls = self._extract_outputs(payload)
                if not urls:
                    raise WaveSpeedError(f"No outputs in WaveSpeed result: {payload}")
                return urls

            if state in _FAILED_STATES:
                fail_msg = data.get("error") or payload.get("message") or "WaveSpeed task failed"
                raise WaveSpeedError(str(fail_msg))

            await asyncio.sleep(sleep_s)
            elapsed += sleep_s
            if elapsed > 30:
                sleep_s = min(10, sleep_s + 3)

        raise WaveSpeedError(f"Task timeout after {max_wait_s}s (taskId={task_id})")

    async def download_bytes(self, url: str) -> bytes:
        async def _do() -> httpx.Response:
            timeout = httpx.Timeout(120.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                return await client.get(url)

        last_exc: Exception | None = None
        max_attempts = 8
        for attempt in range(max_attempts):
            try:
                resp = await _do()
                if resp.status_code != 200:
                    raise WaveSpeedError(
                        f"Download failed [HTTP {resp.status_code}]: {resp.text[:1000]}"
                    )
                return resp.content
            except (
                httpx.TimeoutException,
                httpx.ConnectError,
                httpx.RemoteProtocolError,
            ) as e:
                last_exc = e
                backoff = min(15.0, 2.0 * (attempt + 1))
                await asyncio.sleep(backoff)
            except httpx.HTTPError as e:
                last_exc = e
                break

        raise WaveSpeedError(f"Download failed: {last_exc}")


def get_kie_api_key_from_env() -> str:
    # Keep function name for compatibility with existing imports.
    return (
        os.getenv("WAVESPEED_API_KEY", "").strip()
        or os.getenv("KIE_API_KEY", "").strip()
    )


def get_wavespeed_api_key_from_env() -> str:
    return get_kie_api_key_from_env()


# Backward-compatible aliases.
KieAIError = WaveSpeedError
KieAIClient = WaveSpeedClient
