from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)

WAVESPEED_BASE_URL = "https://api.wavespeed.ai/api/v3"
WAVESPEED_FILE_UPLOAD_URL = f"{WAVESPEED_BASE_URL}/media/upload/binary"
WAVESPEED_PREDICTIONS_URL = f"{WAVESPEED_BASE_URL}/predictions"

KLING_I2V_MODEL = "kwaivgi/kling-v3.0-std/image-to-video"
KLING_MOTION_STD_MODEL = "kwaivgi/kling-v2.6-std/motion-control"
KLING_MOTION_PRO_MODEL = "kwaivgi/kling-v2.6-pro/motion-control"
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


@dataclass(slots=True)
class KieTaskResult:
    state: str
    result_url: Optional[str] = None
    fail_msg: Optional[str] = None


def _loads_json_loose(text: str) -> Any:
    raw = (text or "").strip()
    if not raw:
        raise json.JSONDecodeError("empty json", raw, 0)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # If provider returns multi-line payload, try the last JSON line first.
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    for ln in reversed(lines):
        try:
            return json.loads(ln)
        except json.JSONDecodeError:
            continue

    # Fallback: find first decodable JSON object/array inside text.
    decoder = json.JSONDecoder()
    for i, ch in enumerate(raw):
        if ch not in "{[":
            continue
        try:
            obj, _ = decoder.raw_decode(raw[i:])
            return obj
        except json.JSONDecodeError:
            continue

    raise json.JSONDecodeError("cannot decode json", raw, 0)


async def _read_json_payload(resp: aiohttp.ClientResponse, *, ctx: str) -> dict[str, Any]:
    try:
        data = await resp.json(content_type=None)
    except Exception as e:
        text = await resp.text()
        try:
            data = _loads_json_loose(text)
        except Exception as inner:
            preview = (text or "")[:500].replace("\n", "\\n")
            raise RuntimeError(
                f"{ctx}: invalid JSON response (HTTP {resp.status}): {preview}"
            ) from inner
        if not isinstance(data, dict):
            raise RuntimeError(
                f"{ctx}: unexpected JSON type={type(data).__name__} (HTTP {resp.status})"
            ) from e

    if not isinstance(data, dict):
        raise RuntimeError(
            f"{ctx}: unexpected JSON type={type(data).__name__} (HTTP {resp.status})"
        )
    return data


def _normalize_url_item(item: Any) -> Optional[str]:
    if item is None:
        return None
    if isinstance(item, str):
        return item.strip() or None
    if isinstance(item, dict):
        for k in ("url", "download_url", "downloadUrl", "resultUrl", "href"):
            v = item.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


def _prefer_video_url(urls: list[str]) -> Optional[str]:
    if not urls:
        return None

    preferred_exts = (".mp4", ".mov", ".webm", ".m4v")
    for u in urls:
        base = u.split("?", 1)[0].lower()
        if base.endswith(preferred_exts):
            return u

    for u in urls:
        base = u.split("?", 1)[0].lower()
        if not base.endswith(".gif"):
            return u

    return urls[0]


def _extract_output_url(payload: dict[str, Any]) -> Optional[str]:
    data = payload.get("data") or {}
    outputs = data.get("outputs") or []
    if not isinstance(outputs, list):
        return None

    urls: list[str] = []
    for item in outputs:
        u = _normalize_url_item(item)
        if u:
            urls.append(u)

    return _prefer_video_url(urls)


def _extract_task_status(payload: dict[str, Any]) -> str:
    data = payload.get("data") or {}
    raw = (
        data.get("status")
        or data.get("state")
        or data.get("phase")
        or data.get("task_status")
        or ""
    )
    return str(raw).strip().lower()


class KieKlingClient:
    """
    Backward-compatible wrapper with old class name,
    implemented via WaveSpeed endpoints.
    """

    def __init__(self, api_key: str) -> None:
        self.api_key = (api_key or "").strip()
        self._headers_json = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        self._headers_auth = {"Authorization": f"Bearer {self.api_key}"}

    @staticmethod
    def _extract_task_id(payload: dict[str, Any]) -> Optional[str]:
        data = payload.get("data") or {}
        tid = data.get("id") or data.get("taskId")
        return str(tid) if tid else None

    async def upload_image_bytes(
        self,
        image_bytes: bytes,
        filename: str,
        upload_path: str = "images/wearai/animate",
        timeout_s: int = 180,
    ) -> str:
        del upload_path

        mime_type, _ = mimetypes.guess_type(filename)
        if not mime_type:
            mime_type = "application/octet-stream"

        form = aiohttp.FormData()
        form.add_field("file", image_bytes, filename=filename, content_type=mime_type)

        timeout = aiohttp.ClientTimeout(total=timeout_s)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                WAVESPEED_FILE_UPLOAD_URL,
                headers=self._headers_auth,
                data=form,
            ) as resp:
                data = await _read_json_payload(resp, ctx="WaveSpeed upload")
                if resp.status != 200 or int(data.get("code", 0)) != 200:
                    raise RuntimeError(
                        f"WaveSpeed upload failed: HTTP {resp.status}, payload={data}"
                    )

                out_url = data.get("data", {}).get("download_url")
                if not out_url:
                    raise RuntimeError(
                        f"WaveSpeed upload: no download_url in payload={data}"
                    )

                return str(out_url)

    async def upload_video_bytes(
        self,
        video_bytes: bytes,
        filename: str,
        upload_path: str = "videos/wearai/motion",
        timeout_s: int = 300,
    ) -> str:
        return await self.upload_image_bytes(
            video_bytes,
            filename,
            upload_path=upload_path,
            timeout_s=timeout_s,
        )

    async def create_kling_task(
        self,
        prompt: str,
        image_url: str,
        duration: str = "5",
        negative_prompt: str = "blur, distort, low quality",
        cfg_scale: float = 0.5,
        timeout_s: int = 120,
    ) -> str:
        payload = {
            "image": image_url,
            "prompt": prompt,
            "duration": str(duration or "5"),
            "negative_prompt": negative_prompt,
            "cfg_scale": float(cfg_scale),
            "enable_safety_checker": True,
            "enable_base64_output": False,
            "enable_sync_mode": False,
        }

        url = f"{WAVESPEED_BASE_URL}/{KLING_I2V_MODEL}"

        timeout = aiohttp.ClientTimeout(total=timeout_s)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=self._headers_json, json=payload) as resp:
                data = await _read_json_payload(resp, ctx="WaveSpeed create task")
                if resp.status != 200 or int(data.get("code", 0)) != 200:
                    raise RuntimeError(
                        f"WaveSpeed create task failed: HTTP {resp.status}, payload={data}"
                    )

                task_id = self._extract_task_id(data)
                if not task_id:
                    raise RuntimeError(
                        f"WaveSpeed create task: no id in payload={data}"
                    )
                return task_id

    async def create_motion_control_task(
        self,
        *,
        prompt: str,
        image_url: str,
        video_url: str,
        character_orientation: str = "image",
        mode: str = "std",
        timeout_s: int = 120,
    ) -> str:
        mode_l = (mode or "").strip().lower()
        model = KLING_MOTION_PRO_MODEL if "pro" in mode_l else KLING_MOTION_STD_MODEL

        payload = {
            "image": image_url,
            "video": video_url,
            "prompt": prompt or "",
            "negative_prompt": "",
            "character_orientation": (
                "video"
                if (character_orientation or "").strip().lower() == "video"
                else "image"
            ),
            "keep_original_sound": True,
            "enable_safety_checker": True,
            "enable_base64_output": False,
            "enable_sync_mode": False,
        }

        url = f"{WAVESPEED_BASE_URL}/{model}"

        timeout = aiohttp.ClientTimeout(total=timeout_s)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=self._headers_json, json=payload) as resp:
                data = await _read_json_payload(
                    resp,
                    ctx="WaveSpeed motion-control create task",
                )
                if resp.status != 200 or int(data.get("code", 0)) != 200:
                    raise RuntimeError(
                        "WaveSpeed motion-control create task failed: "
                        f"HTTP {resp.status}, payload={data}"
                    )

                task_id = self._extract_task_id(data)
                if not task_id:
                    raise RuntimeError(
                        f"WaveSpeed motion-control: no id in payload={data}"
                    )
                return task_id

    async def get_task_result(self, task_id: str, timeout_s: int = 30) -> KieTaskResult:
        timeout = aiohttp.ClientTimeout(total=timeout_s)
        url = f"{WAVESPEED_PREDICTIONS_URL}/{task_id}"

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=self._headers_auth) as resp:
                data = await _read_json_payload(resp, ctx="WaveSpeed prediction")
                if resp.status != 200 or int(data.get("code", 0)) != 200:
                    raise RuntimeError(
                        f"WaveSpeed prediction failed: HTTP {resp.status}, payload={data}"
                    )

                d = data.get("data") or {}
                state_l = _extract_task_status(data)
                state = state_l or str(d.get("status") or d.get("state") or "processing")

                if state_l in _FAILED_STATES:
                    fail = str(d.get("error") or data.get("message") or "Generation failed")
                    return KieTaskResult(state=state, fail_msg=fail)

                if state_l in _SUCCESS_STATES:
                    return KieTaskResult(state=state, result_url=_extract_output_url(data))

                return KieTaskResult(state=state or "processing")

    async def to_direct_download_url(self, url: str, timeout_s: int = 30) -> str:
        del timeout_s
        return url

    async def wait_for_success(
        self,
        task_id: str,
        poll_interval_s: int = 10,
        max_wait_s: int = 12 * 60,
    ) -> KieTaskResult:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max_wait_s
        last_state = ""

        while True:
            if loop.time() > deadline:
                return KieTaskResult(
                    state="timeout",
                    fail_msg="Timeout waiting for video generation",
                )

            res = await self.get_task_result(task_id)
            st = res.state.lower()
            if st and st != last_state:
                logger.info("wavespeed: task_id=%s status=%s", task_id, st)
                last_state = st

            if st in _SUCCESS_STATES:
                return res
            if st in _FAILED_STATES:
                return res

            await asyncio.sleep(poll_interval_s)
