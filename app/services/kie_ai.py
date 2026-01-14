from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class PhotoSettingsDTO:
    aspect_ratio: str = "9:16"
    resolution: str = "2K"  # 1K / 2K / 4K
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
    "auto",
}
_ALLOWED_RESOLUTIONS = {"1K", "2K", "4K"}
_ALLOWED_FORMATS = {"png", "jpg"}


def _norm_aspect_ratio(v: str) -> str:
    v = (v or "").strip()
    return v if v in _ALLOWED_ASPECTS else DEFAULT_PHOTO_SETTINGS.aspect_ratio


def _norm_resolution(v: str) -> str:
    v = (v or "").strip().upper()
    return v if v in _ALLOWED_RESOLUTIONS else DEFAULT_PHOTO_SETTINGS.resolution


def _norm_output_format(v: str) -> str:
    v = (v or "").strip().lower()
    if v == "jpeg":
        v = "jpg"
    return v if v in _ALLOWED_FORMATS else DEFAULT_PHOTO_SETTINGS.output_format


async def _load_photo_settings_from_db(
    session: AsyncSession, tg_id: int
) -> PhotoSettingsDTO:
    """
    Читает настройки пользователя из БД по tg_id.
    Ожидается:
      - app.models.user.User (users.tg_id)
      - app.models.user_photo_settings.UserPhotoSettings (user_photo_settings.user_id)
    Если не найдено — DEFAULT_PHOTO_SETTINGS.
    """
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


class KieAIError(RuntimeError):
    pass


def _debug_save_upload_image(data: bytes, filename: str) -> None:
    """
    DEBUG: сохраняет байты картинки, которая уходит в KIE upload.
    Включается env-переменной KIE_DEBUG_SAVE_IMAGES=1

    По умолчанию сохраняет в:
      <cwd>/_kie_debug_uploads/
    Можно переопределить:
      KIE_DEBUG_SAVE_DIR=/path/to/project
    """
    if os.getenv("KIE_DEBUG_SAVE_IMAGES", "0") != "1":
        return

    try:
        root = Path(os.getenv("KIE_DEBUG_SAVE_DIR", str(Path.cwd())))
        out_dir = root / "_kie_debug_uploads"
        out_dir.mkdir(parents=True, exist_ok=True)

        base = Path(filename).name or "image.bin"
        suffix = Path(base).suffix or ".bin"

        out_name = f"kie_upload_{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}{suffix}"
        out_path = out_dir / out_name
        out_path.write_bytes(data)
        print(f"[KIE DEBUG] saved upload image -> {out_path}")
    except Exception as e:
        print(f"[KIE DEBUG] failed to save upload image: {e}")


def _make_unique_upload_target(upload_path: str, filename: str) -> tuple[str, str, str]:
    """
    Делает uploadPath и fileName уникальными, чтобы не ловить кеш по одному URL.
    Можно выключить:
      KIE_UPLOAD_UNIQUE=0
    """
    if os.getenv("KIE_UPLOAD_UNIQUE", "1") != "1":
        return (upload_path or "images/user-uploads"), (filename or "image.png"), ""

    tag = f"{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}"
    base_path = (upload_path or "images/user-uploads").rstrip("/")
    unique_path = f"{base_path}/{tag}"

    p = Path(filename or "image.png")
    stem = p.stem or "image"
    suf = p.suffix or ".png"
    unique_filename = f"{stem}_{tag}{suf}"

    return unique_path, unique_filename, tag


def _add_cache_buster(urls: Sequence[str], tag: str) -> list[str]:
    """
    Добавляет v=... к URL, но только если его там ещё нет.
    Включается env:
      KIE_FORCE_NOCACHE=1
    """
    if os.getenv("KIE_FORCE_NOCACHE", "0") != "1":
        return list(urls)

    v = tag or str(int(time.time() * 1000))
    out: list[str] = []

    for u in urls:
        if not isinstance(u, str) or not u.strip():
            continue

        # если уже есть v=..., не трогаем
        if "v=" in u:
            out.append(u)
            continue

        if "?" in u:
            out.append(f"{u}&v={v}")
        else:
            out.append(f"{u}?v={v}")

    return out


class KieAIClient:
    """
    KIE integration:
      - Upload images -> https://kieai.redpandaai.co/api/file-stream-upload
      - Create task   -> https://api.kie.ai/api/v1/jobs/createTask (model nano-banana-pro)
      - Poll status   -> https://api.kie.ai/api/v1/jobs/recordInfo?taskId=...
    """

    def __init__(
        self,
        api_key: str,
        *,
        api_base: str = "https://api.kie.ai",
        upload_base: str = "https://kieai.redpandaai.co",
        timeout_s: float = 60.0,
    ) -> None:
        if not api_key:
            raise KieAIError("KIE_API_KEY is empty. Put it into .env")
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.upload_base = upload_base.rstrip("/")
        self.timeout = httpx.Timeout(timeout_s)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def upload_image_bytes(
        self,
        *,
        data: bytes,
        filename: str,
        upload_path: str = "images/user-uploads",
    ) -> str:
        """
        Returns public download URL from KIE upload service.
        """
        url = f"{self.upload_base}/api/file-stream-upload"

        unique_upload_path, unique_filename, tag = _make_unique_upload_target(
            upload_path, filename
        )

        # DEBUG: если включено, сохраняем то, что реально уходит в upload
        _debug_save_upload_image(data, unique_filename)

        files = {"file": (unique_filename, data, "application/octet-stream")}
        form = {"uploadPath": unique_upload_path, "fileName": unique_filename}

        if os.getenv("KIE_DEBUG_PRINT_UPLOAD", "0") == "1":
            print(
                "[KIE DEBUG] upload:",
                json.dumps(
                    {
                        "uploadPath": unique_upload_path,
                        "fileName": unique_filename,
                        "tag": tag,
                        "bytes": len(data),
                    },
                    ensure_ascii=False,
                ),
            )

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                url, headers=self._headers(), files=files, data=form
            )
            if resp.status_code != 200:
                raise KieAIError(f"Upload failed [{resp.status_code}]: {resp.text}")

            payload = resp.json()
            if payload.get("code") != 200 or payload.get("success") is not True:
                raise KieAIError(f"Upload failed: {payload}")

            data_obj = payload.get("data") or {}
            download_url = data_obj.get("downloadUrl")
            if not download_url:
                raise KieAIError(f"Upload response has no downloadUrl: {payload}")

            dl = str(download_url)

            # опционально добавляем cache-buster к downloadUrl
            if os.getenv("KIE_FORCE_NOCACHE", "0") == "1" and "v=" not in dl:
                if "?" in dl:
                    dl = f"{dl}&v={tag or int(time.time()*1000)}"
                else:
                    dl = f"{dl}?v={tag or int(time.time()*1000)}"

            return dl

    async def create_nano_banana_pro_task(
        self,
        *,
        prompt: str,
        image_input_urls: Sequence[str],
        settings: PhotoSettingsDTO | None = None,
        session: AsyncSession | None = None,
        tg_id: int | None = None,
        callback_url: str | None = None,
    ) -> str:
        url = f"{self.api_base}/api/v1/jobs/createTask"

        # 1) Если есть session+tg_id — берем настройки из БД (ПРИОРИТЕТНО)
        if session is not None and tg_id is not None:
            try:
                settings = await _load_photo_settings_from_db(
                    session=session, tg_id=tg_id
                )
            except Exception:
                settings = settings or DEFAULT_PHOTO_SETTINGS

        if settings is None:
            settings = DEFAULT_PHOTO_SETTINGS

        aspect_ratio = _norm_aspect_ratio(settings.aspect_ratio)
        resolution = _norm_resolution(settings.resolution)
        output_format = _norm_output_format(settings.output_format)

        # cache-buster к URL (если включено) — только если v= ещё нет
        req_tag = str(int(time.time() * 1000))
        safe_urls = _add_cache_buster(image_input_urls, req_tag)

        body: dict[str, Any] = {
            "model": "nano-banana-pro",
            "input": {
                "prompt": prompt,
                "image_input": list(safe_urls),
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "output_format": output_format,
            },
        }
        if callback_url:
            body["callBackUrl"] = callback_url

        if os.getenv("KIE_DEBUG_PRINT_TASK", "0") == "1":
            try:
                print(
                    "[KIE DEBUG] createTask body:", json.dumps(body, ensure_ascii=False)
                )
            except Exception:
                print("[KIE DEBUG] createTask body:", body)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                url,
                headers={**self._headers(), "Content-Type": "application/json"},
                json=body,
            )
            if resp.status_code != 200:
                raise KieAIError(f"createTask failed [{resp.status_code}]: {resp.text}")

            payload = resp.json()
            if payload.get("code") != 200:
                raise KieAIError(f"createTask failed: {payload}")

            task_id = (payload.get("data") or {}).get("taskId")
            if not task_id:
                raise KieAIError(f"createTask response has no taskId: {payload}")

            return task_id

    async def get_task(self, task_id: str) -> dict[str, Any]:
        url = f"{self.api_base}/api/v1/jobs/recordInfo"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                url, headers=self._headers(), params={"taskId": task_id}
            )
            if resp.status_code != 200:
                raise KieAIError(f"recordInfo failed [{resp.status_code}]: {resp.text}")

            payload = resp.json()
            if payload.get("code") != 200:
                raise KieAIError(f"recordInfo failed: {payload}")

            return payload

    async def wait_result_urls(
        self, task_id: str, *, max_wait_s: int = 600
    ) -> list[str]:
        elapsed = 0
        sleep_s = 2

        while elapsed < max_wait_s:
            payload = await self.get_task(task_id)
            data = payload.get("data") or {}
            state = (data.get("state") or "").strip().lower()

            if state == "success":
                result_json = data.get("resultJson") or ""
                try:
                    result_obj = json.loads(result_json) if result_json else {}
                except json.JSONDecodeError:
                    raise KieAIError(f"Bad resultJson: {result_json}")

                urls = (
                    result_obj.get("resultUrls") or result_obj.get("result_urls") or []
                )
                if not isinstance(urls, list) or not urls:
                    raise KieAIError(f"No resultUrls in resultJson: {result_obj}")
                return [str(u) for u in urls]

            if state == "fail":
                fail_msg = data.get("failMsg") or "KIE task failed"
                fail_code = data.get("failCode") or ""
                raise KieAIError(f"{fail_msg} (code={fail_code})")

            await asyncio.sleep(sleep_s)
            elapsed += sleep_s
            if elapsed > 30:
                sleep_s = min(10, sleep_s + 3)

        raise KieAIError(f"Task timeout after {max_wait_s}s (taskId={task_id})")

    async def download_bytes(self, url: str) -> bytes:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise KieAIError(
                    f"Download failed [{resp.status_code}]: {resp.text[:2000]}"
                )
            return resp.content


def get_kie_api_key_from_env() -> str:
    return os.getenv("KIE_API_KEY", "").strip()
