from __future__ import annotations

from urllib.parse import urlsplit
from typing import Sequence

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.wavespeed_ai import (
    WaveSpeedClient,
    PhotoSettingsDTO,
    get_wavespeed_api_key_from_env,
)
from app.utils.tg_files import tg_file_id_to_bytes


def _normalize_output_format(v: str) -> str:
    v = (v or "").strip().lower()
    if v == "jpeg":
        return "jpg"
    if v not in {"png", "jpg"}:
        return "png"
    return v


def _normalize_resolution(v: str) -> str:
    del v
    return "1K"


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
    }
    if v == "auto" or v not in allowed:
        return "9:16"
    return v


def _guess_image_extension(url: str) -> str:
    path = urlsplit(url).path
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    if ext == "jpeg":
        return "jpg"
    if ext not in {"jpg", "png", "webp"}:
        return "png"
    return ext


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


async def generate_image_wavespeed_from_telegram(
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
    model_variant: str = "nano_banana_2",
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

    wavespeed = WaveSpeedClient(api_key=get_wavespeed_api_key_from_env())

    # 1) TG -> bytes (до max_images)
    safe_max = max(1, min(int(max_images or 0), 10))
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
        url = await wavespeed.upload_image_bytes(
            data=b,
            filename=filename,
            upload_path=f"wearai/{tg_id}",
        )
        uploaded_urls.append(url)

    # 3) createTask (nano-banana-2) — settings уже из БД
    if model_variant == "nano_banana_pro":
        task_id = await wavespeed.create_nano_banana_pro_edit_task(
            prompt=prompt,
            image_input_urls=uploaded_urls,
            settings=settings,
        )
    else:
        task_id = await wavespeed.create_nano_banana_2_task(
            prompt=prompt,
            image_input_urls=uploaded_urls,
            settings=settings,
        )

    # 4) wait -> result urls
    result_urls = await wavespeed.wait_result_urls(task_id)

    # 5) download results -> bytes
    out: list[tuple[str, bytes]] = []
    for idx, url in enumerate(result_urls, start=1):
        img_bytes = await wavespeed.download_bytes(url)
        out.append((f"result_{idx}.{settings.output_format}", img_bytes))

    return out


async def _upload_tg_reference_images(
    *,
    bot: Bot,
    wavespeed: WaveSpeedClient,
    tg_id: int,
    telegram_photo_file_ids: Sequence[str],
    output_format: str,
    max_images: int,
) -> list[str]:
    safe_max = max(0, min(int(max_images or 0), 10))
    file_ids = list(telegram_photo_file_ids)[:safe_max]
    uploaded_urls: list[str] = []

    for idx, fid in enumerate(file_ids, start=1):
        data = await tg_file_id_to_bytes(bot, fid, tg_id=tg_id)
        filename = f"{tg_id}_seedream_{idx}.{output_format}"
        url = await wavespeed.upload_image_bytes(
            data=data,
            filename=filename,
            upload_path=f"wearai/{tg_id}/seedream",
        )
        uploaded_urls.append(url)

    return uploaded_urls


async def generate_seedream_v5_lite(
    *,
    bot: Bot,
    session: AsyncSession,
    tg_id: int,
    prompt: str,
    telegram_photo_file_ids: Sequence[str] = (),
    size: str | None = None,
    output_format: str | None = None,
) -> list[tuple[str, bytes]]:
    settings = await get_user_photo_settings(session, tg_id)
    result_format = _normalize_output_format(output_format or settings.output_format)
    wavespeed = WaveSpeedClient(api_key=get_wavespeed_api_key_from_env())

    uploaded_urls = await _upload_tg_reference_images(
        bot=bot,
        wavespeed=wavespeed,
        tg_id=tg_id,
        telegram_photo_file_ids=telegram_photo_file_ids,
        output_format=result_format,
        max_images=10,
    )

    task_id = await wavespeed.create_seedream_v5_lite_task(
        prompt=prompt,
        reference_image_urls=uploaded_urls,
        size=size,
        output_format=result_format,
        settings=PhotoSettingsDTO(
            aspect_ratio=settings.aspect_ratio,
            resolution=settings.resolution,
            output_format=result_format,
        ),
    )
    result_urls = await wavespeed.wait_result_urls(task_id)

    out: list[tuple[str, bytes]] = []
    for idx, url in enumerate(result_urls, start=1):
        img_bytes = await wavespeed.download_bytes(url)
        out.append((f"result_{idx}.{result_format}", img_bytes))

    return out


async def generate_wan_27_image(
    *,
    session: AsyncSession,
    tg_id: int,
    prompt: str,
    size: str | None = None,
    width: int | None = None,
    height: int | None = None,
    thinking_mode: bool | None = None,
    seed: int | None = None,
) -> list[tuple[str, bytes]]:
    del session, tg_id
    wavespeed = WaveSpeedClient(api_key=get_wavespeed_api_key_from_env())

    task_id = await wavespeed.create_wan_27_text_to_image_task(
        prompt=prompt,
        size=size,
        width=width,
        height=height,
        thinking_mode=thinking_mode,
        seed=seed,
    )
    result_urls = await wavespeed.wait_result_urls(task_id)

    out: list[tuple[str, bytes]] = []
    for idx, url in enumerate(result_urls, start=1):
        img_bytes = await wavespeed.download_bytes(url)
        ext = _guess_image_extension(url)
        out.append((f"result_{idx}.{ext}", img_bytes))

    return out


async def generate_seedream_v45_image(
    *,
    prompt: str,
    size: str | None = None,
) -> list[tuple[str, bytes]]:
    wavespeed = WaveSpeedClient(api_key=get_wavespeed_api_key_from_env())

    task_id = await wavespeed.create_seedream_v45_task(
        prompt=prompt,
        size=size,
    )
    result_urls = await wavespeed.wait_result_urls(task_id)

    out: list[tuple[str, bytes]] = []
    for idx, url in enumerate(result_urls, start=1):
        img_bytes = await wavespeed.download_bytes(url)
        ext = _guess_image_extension(url)
        out.append((f"result_{idx}.{ext}", img_bytes))

    return out


async def generate_gpt_image_2_text_to_image(
    *,
    prompt: str,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    quality: str | None = None,
) -> list[tuple[str, bytes]]:
    wavespeed = WaveSpeedClient(api_key=get_wavespeed_api_key_from_env())

    task_id = await wavespeed.create_gpt_image_2_text_to_image_task(
        prompt=prompt,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        quality=quality,
    )
    result_urls = await wavespeed.wait_result_urls(task_id)

    out: list[tuple[str, bytes]] = []
    for idx, url in enumerate(result_urls, start=1):
        img_bytes = await wavespeed.download_bytes(url)
        ext = _guess_image_extension(url)
        out.append((f"result_{idx}.{ext}", img_bytes))

    return out


async def generate_gpt_image_2_edit_from_telegram(
    *,
    bot: Bot,
    session: AsyncSession,
    tg_id: int,
    prompt: str,
    telegram_photo_file_ids: Sequence[str],
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    quality: str | None = None,
    max_images: int = 5,
) -> list[tuple[str, bytes]]:
    del session
    wavespeed = WaveSpeedClient(api_key=get_wavespeed_api_key_from_env())

    uploaded_urls = await _upload_tg_reference_images(
        bot=bot,
        wavespeed=wavespeed,
        tg_id=tg_id,
        telegram_photo_file_ids=telegram_photo_file_ids,
        output_format="png",
        max_images=max_images,
    )
    task_id = await wavespeed.create_gpt_image_2_edit_task(
        prompt=prompt,
        image_input_urls=uploaded_urls,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        quality=quality,
    )
    result_urls = await wavespeed.wait_result_urls(task_id)

    out: list[tuple[str, bytes]] = []
    for idx, url in enumerate(result_urls, start=1):
        img_bytes = await wavespeed.download_bytes(url)
        ext = _guess_image_extension(url)
        out.append((f"result_{idx}.{ext}", img_bytes))

    return out


async def generate_image_wavespeed_from_telegram_with_extra(
    *,
    bot: Bot,
    session: AsyncSession,
    tg_id: int,
    prompt: str,
    telegram_photo_file_ids: Sequence[str],
    extra_images: Sequence[tuple[str, bytes]] = (),
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    output_format: str | None = None,
    max_images: int = 5,
) -> list[tuple[str, bytes]]:
    """
    Like generate_image_wavespeed_from_telegram, but allows extra input images as raw bytes.
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

    wavespeed = WaveSpeedClient(api_key=get_wavespeed_api_key_from_env())

    max_total_inputs = 8
    extra_list = list(extra_images)[:max_total_inputs]
    available_slots = max(0, max_total_inputs - len(extra_list))

    safe_max = max(0, min(int(max_images or 0), available_slots))
    file_ids = list(telegram_photo_file_ids)[:safe_max]

    images_bytes: list[bytes] = []
    for fid in file_ids:
        b = await tg_file_id_to_bytes(bot, fid, tg_id=tg_id)
        images_bytes.append(b)

    uploaded_urls: list[str] = []
    for idx, (name, data) in enumerate(extra_list, start=1):
        filename = name or f"extra_{idx}.{settings.output_format}"
        url = await wavespeed.upload_image_bytes(
            data=data,
            filename=filename,
            upload_path=f"wearai/{tg_id}",
        )
        uploaded_urls.append(url)

    for i, b in enumerate(images_bytes, start=1):
        filename = f"{tg_id}_{i}.{settings.output_format}"
        url = await wavespeed.upload_image_bytes(
            data=b,
            filename=filename,
            upload_path=f"wearai/{tg_id}",
        )
        uploaded_urls.append(url)

    task_id = await wavespeed.create_nano_banana_2_task(
        prompt=prompt,
        image_input_urls=uploaded_urls,
        settings=settings,
    )

    result_urls = await wavespeed.wait_result_urls(task_id)

    out: list[tuple[str, bytes]] = []
    for idx, url in enumerate(result_urls, start=1):
        img_bytes = await wavespeed.download_bytes(url)
        out.append((f"result_{idx}.{settings.output_format}", img_bytes))

    return out


# Backward-compatible aliases.
generate_image_kie_from_telegram = generate_image_wavespeed_from_telegram
generate_image_kie_from_telegram_with_extra = (
    generate_image_wavespeed_from_telegram_with_extra
)
