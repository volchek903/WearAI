from __future__ import annotations

from typing import Sequence

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.kie_ai import KieAIClient, PhotoSettingsDTO, get_kie_api_key_from_env
from app.utils.tg_files import tg_file_id_to_bytes


def _normalize_output_format(v: str) -> str:
    v = (v or "").strip().lower()
    if v == "jpeg":
        return "jpg"
    if v not in {"png", "jpg"}:
        return "png"
    return v


def _normalize_resolution(v: str) -> str:
    v = (v or "").strip().upper()
    if v not in {"1K", "2K"}:
        return "2K"
    return v


def _normalize_aspect_ratio(v: str) -> str:
    v = (v or "").strip()
    allowed = {
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
    if v not in allowed:
        return "9:16"
    return v


async def get_user_photo_settings(
    session: AsyncSession, tg_id: int
) -> PhotoSettingsDTO:
    """
    Возвращает настройки из user_photo_settings для конкретного tg_id.
    Если записи нет — создаёт дефолтную и возвращает её.

    Требуется:
      - app.models.user.User
      - app.models.user_photo_settings.UserPhotoSettings
    """
    from app.models.user import User
    from app.models.user_photo_settings import UserPhotoSettings

    default = PhotoSettingsDTO()

    # 1) user
    user = await session.scalar(select(User).where(User.tg_id == tg_id))
    if not user:
        # Обычно не должно быть (ты делаешь upsert_user), но пусть будет безопасно
        return default

    # 2) settings
    s = await session.scalar(
        select(UserPhotoSettings).where(UserPhotoSettings.user_id == user.id)
    )

    # 3) если нет — создаём дефолтные
    if s is None:
        s = UserPhotoSettings(
            user_id=user.id,
            aspect_ratio=default.aspect_ratio,
            resolution=default.resolution,
            output_format=default.output_format,
        )
        session.add(s)
        await session.commit()
        await session.refresh(s)

    return PhotoSettingsDTO(
        aspect_ratio=_normalize_aspect_ratio(
            getattr(s, "aspect_ratio", default.aspect_ratio)
        ),
        resolution=_normalize_resolution(getattr(s, "resolution", default.resolution)),
        output_format=_normalize_output_format(
            getattr(s, "output_format", default.output_format)
        ),
    )


async def generate_image_kie_from_telegram(
    *,
    bot: Bot,
    session: AsyncSession,
    tg_id: int,
    prompt: str,
    telegram_photo_file_ids: Sequence[str],
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    output_format: str | None = None,
    max_images: int = 5,
) -> list[tuple[str, bytes]]:
    """
    Returns list of (filename, bytes) of generated images.
    """
    settings = await get_user_photo_settings(session, tg_id)
    if aspect_ratio or resolution or output_format:
        settings = PhotoSettingsDTO(
            aspect_ratio=_normalize_aspect_ratio(
                aspect_ratio or settings.aspect_ratio
            ),
            resolution=_normalize_resolution(resolution or settings.resolution),
            output_format=_normalize_output_format(
                output_format or settings.output_format
            ),
        )

    kie = KieAIClient(api_key=get_kie_api_key_from_env())

    # 1) TG -> bytes (до max_images)
    safe_max = max(1, min(int(max_images or 0), 8))
    file_ids = list(telegram_photo_file_ids)[:safe_max]
    images_bytes: list[bytes] = []
    for fid in file_ids:
        # tg_file_id_to_bytes требует keyword-only аргумент tg_id
        b = await tg_file_id_to_bytes(bot, fid, tg_id=tg_id)
        images_bytes.append(b)

    # 2) upload -> urls
    uploaded_urls: list[str] = []
    for i, b in enumerate(images_bytes, start=1):
        # имя файла на upload не обязано совпадать с форматом результата,
        # но так удобнее для дебага.
        filename = f"{tg_id}_{i}.{settings.output_format}"
        url = await kie.upload_image_bytes(
            data=b,
            filename=filename,
            upload_path=f"wearai/{tg_id}",
        )
        uploaded_urls.append(url)

    # 3) createTask (nano-banana-pro) — settings уже из БД
    task_id = await kie.create_nano_banana_pro_task(
        prompt=prompt,
        image_input_urls=uploaded_urls,
        settings=settings,
    )

    # 4) wait -> result urls
    result_urls = await kie.wait_result_urls(task_id)

    # 5) download results -> bytes
    out: list[tuple[str, bytes]] = []
    for idx, url in enumerate(result_urls, start=1):
        img_bytes = await kie.download_bytes(url)
        out.append((f"result_{idx}.{settings.output_format}", img_bytes))

    return out
