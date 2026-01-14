from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)

KIE_FILE_UPLOAD_URL = "https://kieai.redpandaai.co/api/file-stream-upload"
KIE_CREATE_TASK_URL = "https://api.kie.ai/api/v1/jobs/createTask"
KIE_TASK_INFO_URL = "https://api.kie.ai/api/v1/jobs/recordInfo"
KIE_DOWNLOAD_URL = "https://api.kie.ai/api/v1/common/download-url"

KLING_MODEL = "kling/v2-1-standard"


@dataclass(slots=True)
class KieTaskResult:
    state: str
    result_url: Optional[str] = None
    fail_msg: Optional[str] = None


def _as_json_obj(value: Any) -> Optional[Any]:
    """
    KIE чаще отдаёт resultJson строкой, но на практике может быть и dict/list.
    Приводим к объекту Python, если возможно.
    """
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except Exception:
            return None
    # На всякий случай
    try:
        return json.loads(str(value))
    except Exception:
        return None


def _normalize_url_item(item: Any) -> Optional[str]:
    """
    В resultUrls элементы могут быть строками или объектами.
    Пробуем извлечь URL.
    """
    if item is None:
        return None
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for k in ("url", "resultUrl", "videoUrl", "downloadUrl", "href"):
            v = item.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


def _prefer_video_url(urls: list[str]) -> Optional[str]:
    """
    Предпочитаем "настоящий" видеоконтейнер, а не gif-превью.
    """
    if not urls:
        return None

    preferred_exts = (".mp4", ".mov", ".webm", ".m4v")
    for u in urls:
        base = u.split("?", 1)[0].lower()
        if base.endswith(preferred_exts):
            return u

    # Если нет "явного" расширения — стараемся хотя бы не gif
    for u in urls:
        base = u.split("?", 1)[0].lower()
        if not base.endswith(".gif"):
            return u

    return urls[0]


def _pick_result_url(result_json_value: Any) -> Optional[str]:
    """
    Достаёт ссылку на результат из resultJson.
    Приоритет: видео (mp4/mov/webm), затем любая другая ссылка.
    """
    payload = _as_json_obj(result_json_value)
    if payload is None:
        return None

    # 1) Наиболее частый формат: {"resultUrls": ["...", "..."]}
    if isinstance(payload, dict):
        urls_raw = payload.get("resultUrls")
        if isinstance(urls_raw, list) and urls_raw:
            urls: list[str] = []
            for it in urls_raw:
                u = _normalize_url_item(it)
                if u:
                    urls.append(u)
            picked = _prefer_video_url(urls)
            if picked:
                return picked

        # 2) Запасные ключи (иногда отдают одной строкой)
        for key in ("resultUrl", "videoUrl", "video_url", "url", "outputUrl"):
            v = payload.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()

        # 3) Иногда бывает вложенность: {"data": {"resultUrls": [...]}}
        data = payload.get("data")
        if isinstance(data, dict):
            urls_raw = data.get("resultUrls")
            if isinstance(urls_raw, list) and urls_raw:
                urls: list[str] = []
                for it in urls_raw:
                    u = _normalize_url_item(it)
                    if u:
                        urls.append(u)
                picked = _prefer_video_url(urls)
                if picked:
                    return picked

    # 4) Если payload — список URL’ов
    if isinstance(payload, list):
        urls: list[str] = []
        for it in payload:
            u = _normalize_url_item(it)
            if u:
                urls.append(u)
        picked = _prefer_video_url(urls)
        if picked:
            return picked

    return None


class KieKlingClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key.strip()
        self._headers_json = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        self._headers_auth = {"Authorization": f"Bearer {self.api_key}"}

    async def upload_image_bytes(
        self,
        image_bytes: bytes,
        filename: str,
        upload_path: str = "images/wearai/animate",
        timeout_s: int = 60,
    ) -> str:
        """
        Загружает файл в KIE File Upload API (stream) и возвращает публичный downloadUrl.
        """
        mime_type, _ = mimetypes.guess_type(filename)
        if not mime_type:
            mime_type = "application/octet-stream"

        form = aiohttp.FormData()
        form.add_field("file", image_bytes, filename=filename, content_type=mime_type)
        form.add_field("uploadPath", upload_path)
        form.add_field("fileName", filename)

        timeout = aiohttp.ClientTimeout(total=timeout_s)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            logger.info(
                "KIE upload start: filename=%s upload_path=%s", filename, upload_path
            )
            async with session.post(
                KIE_FILE_UPLOAD_URL,
                headers=self._headers_auth,
                data=form,
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status != 200 or not data.get("success"):
                    logger.error(
                        "KIE upload failed: http=%s payload=%s", resp.status, data
                    )
                    raise RuntimeError(
                        f"KIE upload failed: HTTP {resp.status}, payload={data}"
                    )

                download_url = data.get("data", {}).get("downloadUrl")
                if not download_url:
                    logger.error("KIE upload missing downloadUrl: payload=%s", data)
                    raise RuntimeError(f"KIE upload: no downloadUrl in payload={data}")

                logger.info("KIE upload ok: downloadUrl=%s", download_url)
                return str(download_url)

    async def create_kling_task(
        self,
        prompt: str,
        image_url: str,
        duration: str = "5",
        negative_prompt: str = "blur, distort, low quality",
        cfg_scale: float = 0.5,
        timeout_s: int = 60,
    ) -> str:
        """
        Создаёт задачу Kling v2.1 Standard и возвращает taskId.
        duration: "5" или "10"
        """
        payload = {
            "model": KLING_MODEL,
            "input": {
                "prompt": prompt,
                "image_url": image_url,
                "duration": duration,
                "negative_prompt": negative_prompt,
                "cfg_scale": cfg_scale,
            },
        }

        timeout = aiohttp.ClientTimeout(total=timeout_s)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            logger.info(
                "KIE createTask start: model=%s duration=%s cfg_scale=%s prompt_len=%s",
                KLING_MODEL,
                duration,
                cfg_scale,
                len(prompt or ""),
            )
            async with session.post(
                KIE_CREATE_TASK_URL,
                headers=self._headers_json,
                json=payload,
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status != 200 or data.get("code") != 200:
                    logger.error(
                        "KIE createTask failed: http=%s payload=%s", resp.status, data
                    )
                    raise RuntimeError(
                        f"KIE createTask failed: HTTP {resp.status}, payload={data}"
                    )

                task_id = (data.get("data") or {}).get("taskId")
                if not task_id:
                    logger.error("KIE createTask missing taskId: payload=%s", data)
                    raise RuntimeError(f"KIE createTask: no taskId in payload={data}")

                logger.info("KIE createTask ok: taskId=%s", task_id)
                return str(task_id)

    async def get_task_result(self, task_id: str, timeout_s: int = 30) -> KieTaskResult:
        """
        Возвращает состояние и (если готово) ссылку на результат.
        """
        timeout = aiohttp.ClientTimeout(total=timeout_s)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                KIE_TASK_INFO_URL,
                headers=self._headers_auth,
                params={"taskId": task_id},
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status != 200 or data.get("code") != 200:
                    logger.error(
                        "KIE recordInfo failed: http=%s payload=%s", resp.status, data
                    )
                    raise RuntimeError(
                        f"KIE recordInfo failed: HTTP {resp.status}, payload={data}"
                    )

                d = data.get("data") or {}
                state = str(d.get("state") or "")
                state_l = state.lower()

                if state_l in {"fail", "failed"}:
                    fail = str(d.get("failMsg") or "Generation failed")
                    logger.warning("KIE task failed: taskId=%s fail=%s", task_id, fail)
                    return KieTaskResult(state=state, fail_msg=fail)

                if state_l in {"success", "succeed", "done"}:
                    result_json = d.get("resultJson")
                    url = _pick_result_url(result_json)
                    logger.info(
                        "KIE task success: taskId=%s result_url=%s", task_id, url
                    )
                    return KieTaskResult(state=state, result_url=url)

                # queued / running / processing etc.
                logger.info("KIE task state: taskId=%s state=%s", task_id, state)
                return KieTaskResult(state=state)

    async def to_direct_download_url(self, url: str, timeout_s: int = 30) -> str:
        """
        Конвертирует kie.ai generated URL в прямой временный download URL (20 минут).
        Если конвертация не нужна/не проходит — вернёт исходный url.
        """
        payload = {"url": url}
        timeout = aiohttp.ClientTimeout(total=timeout_s)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                KIE_DOWNLOAD_URL,
                headers=self._headers_json,
                json=payload,
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status == 200 and data.get("code") == 200 and data.get("data"):
                    direct = str(data["data"])
                    logger.info("KIE download-url ok: %s -> %s", url, direct)
                    return direct

        logger.info("KIE download-url passthrough: %s", url)
        return url

    async def wait_for_success(
        self,
        task_id: str,
        poll_interval_s: int = 10,
        max_wait_s: int = 12 * 60,
    ) -> KieTaskResult:
        """
        Polling до success/fail или таймаута.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max_wait_s

        while True:
            if loop.time() > deadline:
                logger.warning("KIE task timeout: taskId=%s", task_id)
                return KieTaskResult(
                    state="timeout", fail_msg="Timeout waiting for video generation"
                )

            res = await self.get_task_result(task_id)
            st = res.state.lower()

            if st in {"success", "succeed", "done"}:
                return res
            if st in {"fail", "failed"}:
                return res

            await asyncio.sleep(poll_interval_s)
