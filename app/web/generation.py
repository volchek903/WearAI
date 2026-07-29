from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.video_models import VIDEO_MODEL_CATALOG, get_video_model
from app.handlers.agent import _effective_agent_settings
from app.handlers.car_in_hand import HAND_OPTIONS, _build_prompt as build_car_in_hand_prompt
from app.handlers.cinema_bw import _PROMPT as CINEMA_BW_PROMPT
from app.handlers.disney_family_heart import _build_prompt as build_disney_heart_prompt
from app.handlers.disney_family_wall import _build_prompt as build_disney_wall_prompt
from app.handlers.drift_heart import _PROMPT as DRIFT_HEART_PROMPT
from app.handlers.feb23 import _PROMPT as FEB23_PROMPT
from app.handlers.glam_collage import _PROMPT as GLAM_COLLAGE_PROMPT
from app.handlers.gpt_image_2 import _provider_cost as gpt_provider_cost
from app.handlers.gta_style import (
    _PROMPT as GTA_PROMPT,
    _load_gta_background_bytes,
)
from app.handlers.lego_style import _PROMPT as LEGO_PROMPT
from app.handlers.main_defender import _PROMPT as MAIN_DEFENDER_PROMPT
from app.handlers.march8 import _prompt_with_text as build_march8_prompt
from app.handlers.music_ace_step import (
    DEFAULT_SEED,
    SECTION_LABELS,
    _selected_tag_labels,
)
from app.handlers.radar import RADAR_BASE_PROMPT
from app.handlers.rear_view_mirror import _PROMPT as REAR_VIEW_MIRROR_PROMPT
from app.handlers.second_life import _PROMPT as SECOND_LIFE_PROMPT
from app.handlers.sims_style import (
    _PROMPT as SIMS_PROMPT,
    _load_sims_template_bytes,
)
from app.repository.agent_documents import add_agent_document, list_agent_documents
from app.repository.agent_memory import add_agent_message, list_recent_agent_messages
from app.repository.agent_settings import ensure_agent_settings, snapshot_agent_settings
from app.repository.app_settings import (
    MODEL_PRICE_ACE_STEP_KEY,
    MODEL_PRICE_GPT_IMAGE_2_EDIT_KEY,
    MODEL_PRICE_GPT_IMAGE_2_TEXT_TO_IMAGE_KEY,
    MODEL_PRICE_KLING_I2V_KEY,
    MODEL_PRICE_KLING_MOTION_KEY,
    MODEL_PRICE_NANO_BANANA_KEY,
    MODEL_PRICE_NANO_BANANA_PRO_KEY,
    MODEL_PRICE_SEEDREAM_V45_KEY,
    MODEL_PRICE_SEEDREAM_V5_LITE_KEY,
    MODEL_PRICE_WAN_27_KEY,
    build_agent_price_breakdown,
    get_agent_request_pricing,
    get_model_price_credits,
    get_scaled_model_price_credits,
)
from app.repository.generations import (
    CHARGE_SOURCE_DAILY_FREE,
    NoGenerationsLeft,
    charge_agent_request,
    charge_photo_generation,
    charge_video_generation,
    finalize_agent_request,
    refund_agent_request,
    refund_photo_generation,
    refund_video_generation,
)
from app.repository.users import increment_generated_photos, increment_generated_videos
from app.services.generation import (
    generate_gpt_image_2_edit_from_bytes,
    generate_gpt_image_2_text_to_image,
    generate_image_wavespeed_from_bytes,
    generate_image_wavespeed_from_bytes_with_extra,
    generate_seedream_v45_image,
    generate_seedream_v5_lite_from_bytes,
    generate_wan_27_image,
)
from app.services.wea_agent import (
    extract_document_text,
    generate_agent_reply_streaming,
    search_web,
)
from app.services.wavespeed import WaveSpeedAceStepClient
from app.services.wavespeed_ai import WaveSpeedClient, WaveSpeedError, get_wavespeed_api_key_from_env
from app.utils.formatters import compile_song_lyrics
from app.utils.generated_files import save_generated_binary_bytes, save_generated_image_bytes
from app.utils.kie_kling_client import KieKlingClient
from app.web.session import ensure_web_user


class WebGenerationError(RuntimeError):
    pass


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_optional_int(value: Any) -> int | None:
    if value in (None, "", "null"):
        return None
    return int(value)


def _infer_filename(url: str, *, fallback: str) -> str:
    parsed = urlparse(url)
    name = Path(parsed.path).name
    return name or fallback


def _build_love_is_prompt(text: str) -> str:
    safe_text = (text or "").strip()
    return (
        "Сделай вертикальное фото в формате 3:4. Романтическая иллюстрация "
        "в стиле культовых открыток “Love is…”, выполненная как аккуратный "
        "рисованный арт. Персонажи срисованы по исходной фотографии, их поза "
        "полностью сохранена с сохранением сходства лиц, прически и пропорций, "
        "но в иллюстрированной манере. Молодая влюблённая пара, нежная и уютная "
        "атмосфера. Стиль — чистые контуры, плавные линии, слегка упрощённые "
        "черты лица, большие выразительные глаза, аккуратные нос и губы, "
        "как в классических открытках Love is…. Цвета тёплые, пастельные, "
        "мягкие, без резких контрастов. Композиция как у открытки: — персонажи "
        "в центре кадра — романтический сюжет (объятия, близость, совместный "
        "момент, ощущение любви и заботы) — фон минималистичный или слегка "
        "детализированный, не отвлекающий. В верхней части открытки крупная "
        "надпись: “Love is…” шрифт — рукописный, мультяшный, чёрного цвета с "
        "маленьким сердечком. В нижней части открытки — подпись "
        f"в стиле Love is: “{safe_text}” Иллюстрация выглядит как готовая "
        "печатная открытка ко Дню святого Валентина, высокое качество, чистый "
        "белый фон, мягкий свет, лёгкая романтическая атмосфера, чувство любви, "
        "нежности и уюта. Стиль: romantic illustration, love is style, valentine postcard."
    )


def _build_tryon_prompt(style_prompt: str) -> str:
    return (
        "Create a photorealistic virtual try-on result.\n"
        "Use the first image as the person reference (keep face/body identity).\n"
        "Use the second image as the clothing/item reference (keep colors, fabric, prints, logos).\n"
        "Ensure realistic fit, folds, lighting, and proportions. High quality.\n"
        "No extra accessories unless present in the source images.\n"
        f"\nUser instruction (RU): {(style_prompt or '').strip()}\n"
    )


def _build_model_prompt(model_desc: str, action_desc: str) -> str:
    return (
        f"{(model_desc or '').strip()}\n\n"
        f"{(action_desc or '').strip()}\n\n"
        "Важно: товар должен строго соответствовать референс-фото "
        "(цвет, фактура, форма, принты/логотипы). "
        "Фотореализм, корректные пропорции, естественный свет, высокое качество."
    )


def _build_radar_prompt(car: str, plates: str, people_action: str, location: str) -> str:
    return (
        f"{RADAR_BASE_PROMPT}\n"
        "Детали от пользователя:\n"
        f"Машина: {(car or '').strip()}\n"
        f"Номер: {(plates or '').strip()}\n"
        f"Действия людей: {(people_action or '').strip()}\n"
        f"Локация: {(location or '').strip()}\n"
        "Лица должны быть детально прорисованы на основе фотографий пользователя.\n"
    )


def _save_image_results(
    *,
    results: Sequence[tuple[str, bytes]],
    scenario: str,
    tg_id: int,
) -> list[dict[str, str]]:
    assets: list[dict[str, str]] = []
    for filename, img_bytes in results:
        path = save_generated_image_bytes(
            img_bytes=img_bytes,
            filename=filename,
            scenario=scenario,
            tg_id=tg_id,
        )
        assets.append(
            {
                "kind": "image",
                "filename": filename,
                "path": path,
            }
        )
    return assets


def _save_binary_result(
    *,
    data: bytes,
    filename: str,
    scenario: str,
    tg_id: int,
    kind: str,
) -> list[dict[str, str]]:
    path = save_generated_binary_bytes(
        data=data,
        filename=filename,
        scenario=scenario,
        tg_id=tg_id,
    )
    return [
        {
            "kind": kind,
            "filename": filename,
            "path": path,
        }
    ]


async def generate_photo_mode(
    session: AsyncSession,
    *,
    client_id: str,
    mode_id: str,
    fields: dict[str, Any],
    uploads: Sequence[tuple[str, bytes]],
) -> dict[str, Any]:
    user = await ensure_web_user(session, client_id=client_id)
    tg_id = user.tg_id
    mode = (mode_id or "").strip()
    credits_override: int | None = None
    model_key = MODEL_PRICE_NANO_BANANA_KEY

    if mode == "nano_banana_pro":
        model_key = MODEL_PRICE_NANO_BANANA_PRO_KEY
    elif mode == "seedream_lite":
        model_key = MODEL_PRICE_SEEDREAM_V5_LITE_KEY
    elif mode == "seedream_45":
        model_key = MODEL_PRICE_SEEDREAM_V45_KEY
    elif mode == "wan_27":
        model_key = MODEL_PRICE_WAN_27_KEY
    elif mode == "gpt_image_2_edit":
        model_key = MODEL_PRICE_GPT_IMAGE_2_EDIT_KEY
        credits_override = await get_scaled_model_price_credits(
            session,
            model_key,
            gpt_provider_cost(
                "edit",
                str(fields.get("resolution") or "1k").lower(),
                str(fields.get("quality") or "medium").lower(),
            ),
        )
    elif mode == "gpt_image_2_text_to_image":
        model_key = MODEL_PRICE_GPT_IMAGE_2_TEXT_TO_IMAGE_KEY
        credits_override = await get_scaled_model_price_credits(
            session,
            model_key,
            gpt_provider_cost(
                "text_to_image",
                str(fields.get("resolution") or "1k").lower(),
                str(fields.get("quality") or "medium").lower(),
            ),
        )

    try:
        await charge_photo_generation(
            session,
            tg_id,
            model_key=model_key,
            credits_override=credits_override,
        )
    except NoGenerationsLeft as exc:
        raise WebGenerationError("Недостаточно кредитов для фото-режима.") from exc

    try:
        if mode == "nano_banana":
            results = await generate_image_wavespeed_from_bytes(
                session=session,
                tg_id=tg_id,
                prompt=str(fields.get("prompt") or "").strip(),
                image_inputs=uploads,
                max_images=8,
                model_variant="nano_banana_2",
            )
        elif mode == "nano_banana_pro":
            results = await generate_image_wavespeed_from_bytes(
                session=session,
                tg_id=tg_id,
                prompt=str(fields.get("prompt") or "").strip(),
                image_inputs=uploads,
                max_images=10,
                model_variant="nano_banana_pro",
            )
        elif mode == "seedream_lite":
            size = str(fields.get("size") or "").strip()
            width = _as_optional_int(fields.get("width"))
            height = _as_optional_int(fields.get("height"))
            if width and height:
                size = f"{width}*{height}"
            results = await generate_seedream_v5_lite_from_bytes(
                session=session,
                tg_id=tg_id,
                prompt=str(fields.get("prompt") or "").strip(),
                image_inputs=uploads,
                size=size or None,
                output_format=str(fields.get("output_format") or "png").lower(),
            )
        elif mode == "seedream_45":
            size = str(fields.get("size") or "").strip()
            results = await generate_seedream_v45_image(
                prompt=str(fields.get("prompt") or "").strip(),
                size=size or None,
            )
        elif mode == "wan_27":
            results = await generate_wan_27_image(
                session=session,
                tg_id=tg_id,
                prompt=str(fields.get("prompt") or "").strip(),
                size=str(fields.get("size") or "").strip() or None,
                width=_as_optional_int(fields.get("width")),
                height=_as_optional_int(fields.get("height")),
                thinking_mode=_as_bool(fields.get("thinking_mode")),
                seed=_as_optional_int(fields.get("seed")),
            )
        elif mode == "gpt_image_2_edit":
            results = await generate_gpt_image_2_edit_from_bytes(
                tg_id=tg_id,
                prompt=str(fields.get("prompt") or "").strip(),
                image_inputs=uploads,
                aspect_ratio=str(fields.get("aspect_ratio") or "auto"),
                resolution=str(fields.get("resolution") or "1k"),
                quality=str(fields.get("quality") or "medium"),
                max_images=5,
            )
        elif mode == "gpt_image_2_text_to_image":
            results = await generate_gpt_image_2_text_to_image(
                prompt=str(fields.get("prompt") or "").strip(),
                aspect_ratio=str(fields.get("aspect_ratio") or "1:1"),
                resolution=str(fields.get("resolution") or "1k"),
                quality=str(fields.get("quality") or "medium"),
            )
        elif mode == "tryon":
            if len(uploads) != 2:
                raise WebGenerationError("Для try-on нужны ровно 2 изображения.")
            results = await generate_image_wavespeed_from_bytes(
                session=session,
                tg_id=tg_id,
                prompt=_build_tryon_prompt(str(fields.get("style_prompt") or "")),
                image_inputs=uploads,
                max_images=2,
            )
        elif mode == "model_with_product":
            results = await generate_image_wavespeed_from_bytes(
                session=session,
                tg_id=tg_id,
                prompt=_build_model_prompt(
                    str(fields.get("model_desc") or ""),
                    str(fields.get("presentation_desc") or ""),
                ),
                image_inputs=uploads,
                max_images=5,
            )
        elif mode == "love_is":
            results = await generate_image_wavespeed_from_bytes(
                session=session,
                tg_id=tg_id,
                prompt=_build_love_is_prompt(str(fields.get("love_text") or "")),
                image_inputs=uploads,
                aspect_ratio="3:4",
                max_images=2,
            )
        elif mode == "march8":
            results = await generate_image_wavespeed_from_bytes(
                session=session,
                tg_id=tg_id,
                prompt=build_march8_prompt(str(fields.get("caption_text") or "")),
                image_inputs=uploads,
                aspect_ratio="9:16",
                max_images=2,
            )
        elif mode == "car_in_hand":
            hand_key = str(fields.get("hand_option") or "male_glove")
            hand_desc = HAND_OPTIONS.get(hand_key)
            if not hand_desc:
                raise WebGenerationError("Некорректный вариант руки.")
            results = await generate_image_wavespeed_from_bytes(
                session=session,
                tg_id=tg_id,
                prompt=build_car_in_hand_prompt(
                    str(fields.get("background") or "").strip(),
                    hand_desc,
                ),
                image_inputs=uploads,
                max_images=1,
            )
        elif mode == "radar":
            results = await generate_image_wavespeed_from_bytes(
                session=session,
                tg_id=tg_id,
                prompt=_build_radar_prompt(
                    str(fields.get("car") or ""),
                    str(fields.get("plates") or ""),
                    str(fields.get("people_action") or ""),
                    str(fields.get("location") or ""),
                ),
                image_inputs=uploads,
                max_images=8,
            )
        elif mode == "drift_heart":
            results = await generate_image_wavespeed_from_bytes(
                session=session,
                tg_id=tg_id,
                prompt=DRIFT_HEART_PROMPT,
                image_inputs=uploads,
                aspect_ratio="9:16",
                max_images=1,
            )
        elif mode == "rear_view_mirror":
            results = await generate_image_wavespeed_from_bytes(
                session=session,
                tg_id=tg_id,
                prompt=REAR_VIEW_MIRROR_PROMPT,
                image_inputs=uploads,
                aspect_ratio="9:16",
                max_images=1,
            )
        elif mode == "disney_family_heart":
            results = await generate_image_wavespeed_from_bytes(
                session=session,
                tg_id=tg_id,
                prompt=build_disney_heart_prompt(len(uploads)),
                image_inputs=uploads,
                max_images=8,
            )
        elif mode == "disney_family_wall":
            results = await generate_image_wavespeed_from_bytes(
                session=session,
                tg_id=tg_id,
                prompt=build_disney_wall_prompt(len(uploads)),
                image_inputs=uploads,
                max_images=8,
            )
        elif mode == "main_defender":
            results = await generate_image_wavespeed_from_bytes(
                session=session,
                tg_id=tg_id,
                prompt=MAIN_DEFENDER_PROMPT,
                image_inputs=uploads,
                aspect_ratio="3:4",
                max_images=2,
            )
        elif mode == "cinema_bw":
            results = await generate_image_wavespeed_from_bytes(
                session=session,
                tg_id=tg_id,
                prompt=CINEMA_BW_PROMPT,
                image_inputs=uploads,
                resolution="2K",
                max_images=2,
            )
        elif mode == "second_life":
            results = await generate_image_wavespeed_from_bytes(
                session=session,
                tg_id=tg_id,
                prompt=SECOND_LIFE_PROMPT,
                image_inputs=uploads,
                aspect_ratio="9:16",
                max_images=1,
            )
        elif mode == "feb23":
            results = await generate_image_wavespeed_from_bytes(
                session=session,
                tg_id=tg_id,
                prompt=FEB23_PROMPT,
                image_inputs=uploads,
                aspect_ratio="9:16",
                max_images=2,
            )
        elif mode == "gta_style":
            results = await generate_image_wavespeed_from_bytes_with_extra(
                session=session,
                tg_id=tg_id,
                prompt=GTA_PROMPT,
                image_inputs=uploads,
                extra_images=[("gta_fon.png", _load_gta_background_bytes())],
                aspect_ratio="16:9",
                max_images=1,
            )
        elif mode == "lego_style":
            results = await generate_image_wavespeed_from_bytes(
                session=session,
                tg_id=tg_id,
                prompt=LEGO_PROMPT,
                image_inputs=uploads,
                max_images=1,
            )
        elif mode == "sims_style":
            results = await generate_image_wavespeed_from_bytes_with_extra(
                session=session,
                tg_id=tg_id,
                prompt=SIMS_PROMPT,
                image_inputs=uploads,
                extra_images=[("sims_maket.jpeg", _load_sims_template_bytes())],
                max_images=1,
            )
        elif mode == "glam_collage":
            results = await generate_image_wavespeed_from_bytes(
                session=session,
                tg_id=tg_id,
                prompt=GLAM_COLLAGE_PROMPT,
                image_inputs=uploads,
                aspect_ratio="3:4",
                max_images=1,
            )
        else:
            raise WebGenerationError(f"Неизвестный photo mode: {mode}")

        assets = _save_image_results(results=results, scenario=mode, tg_id=tg_id)
        await increment_generated_photos(
            session=session,
            tg_id=tg_id,
            delta=1,
            section=mode,
        )
        return {"assets": assets, "mode_id": mode, "kind": "photo"}
    except WebGenerationError:
        await refund_photo_generation(session, tg_id, model_key=model_key)
        raise
    except WaveSpeedError as exc:
        await refund_photo_generation(session, tg_id, model_key=model_key)
        raise WebGenerationError(str(exc)) from exc
    except Exception as exc:
        await refund_photo_generation(session, tg_id, model_key=model_key)
        raise WebGenerationError("Не удалось завершить фото-генерацию.") from exc


async def generate_video_mode(
    session: AsyncSession,
    *,
    client_id: str,
    mode_id: str,
    fields: dict[str, Any],
    uploads: Sequence[tuple[str, bytes]],
) -> dict[str, Any]:
    user = await ensure_web_user(session, client_id=client_id)
    tg_id = user.tg_id
    mode = (mode_id or "").strip()

    if mode == "animate_photo":
        try:
            await charge_video_generation(session, tg_id, model_key=MODEL_PRICE_KLING_I2V_KEY)
        except NoGenerationsLeft as exc:
            raise WebGenerationError("Недостаточно кредитов для генерации видео.") from exc
        try:
            filename, image_bytes = uploads[0]
            client = KieKlingClient(get_wavespeed_api_key_from_env())
            image_url = await client.upload_image_bytes(
                image_bytes=image_bytes,
                filename=filename or "photo.jpg",
                upload_path=f"images/wearai/animate/{tg_id}",
            )
            task_id = await client.create_kling_task(
                prompt=str(fields.get("prompt") or "").strip(),
                image_url=image_url,
                duration="5",
            )
            result = await client.wait_for_success(task_id, poll_interval_s=10, max_wait_s=30 * 60)
            if not result.result_url:
                raise WebGenerationError("Видео не вернулось из провайдера.")
            video_bytes = await WaveSpeedClient(api_key=get_wavespeed_api_key_from_env()).download_bytes(result.result_url)
            out_name = _infer_filename(result.result_url, fallback="animation.mp4")
            assets = _save_binary_result(
                data=video_bytes,
                filename=out_name,
                scenario=mode,
                tg_id=tg_id,
                kind="video",
            )
            await increment_generated_videos(session=session, tg_id=tg_id, delta=1, section=mode)
            return {"assets": assets, "mode_id": mode, "kind": "video"}
        except Exception as exc:
            await refund_video_generation(session, tg_id, model_key=MODEL_PRICE_KLING_I2V_KEY)
            raise WebGenerationError("Не удалось оживить фото.") from exc

    if mode == "motion_control":
        duration_s = max(3, int(fields.get("video_duration_s") or 3))
        charged_seconds = max(3, ((duration_s + 2) // 3) * 3)
        credits_per_second = max(
            1,
            await get_model_price_credits(session, MODEL_PRICE_KLING_MOTION_KEY) // 3
            + (1 if await get_model_price_credits(session, MODEL_PRICE_KLING_MOTION_KEY) % 3 else 0),
        )
        total_credits = credits_per_second * charged_seconds
        try:
            await charge_video_generation(
                session,
                tg_id,
                model_key=MODEL_PRICE_KLING_MOTION_KEY,
                credits_override=total_credits,
            )
        except NoGenerationsLeft as exc:
            raise WebGenerationError("Недостаточно кредитов для motion control.") from exc
        try:
            image_name, image_bytes = uploads[0]
            video_name, video_bytes = uploads[1]
            client = KieKlingClient(get_wavespeed_api_key_from_env())
            image_url = await client.upload_image_bytes(
                image_bytes=image_bytes,
                filename=image_name or "motion.jpg",
                upload_path=f"images/wearai/motion/{tg_id}",
            )
            video_url = await client.upload_video_bytes(
                video_bytes=video_bytes,
                filename=video_name or "reference.mp4",
                upload_path=f"videos/wearai/motion/{tg_id}",
            )
            task_id = await client.create_motion_control_task(
                prompt=str(fields.get("prompt") or "").strip(),
                image_url=image_url,
                video_url=video_url,
            )
            result = await client.wait_for_success(task_id, poll_interval_s=10, max_wait_s=30 * 60)
            if not result.result_url:
                raise WebGenerationError("Motion-control видео не вернулось.")
            video_out = await WaveSpeedClient(api_key=get_wavespeed_api_key_from_env()).download_bytes(result.result_url)
            out_name = _infer_filename(result.result_url, fallback="motion_control.mp4")
            assets = _save_binary_result(
                data=video_out,
                filename=out_name,
                scenario=mode,
                tg_id=tg_id,
                kind="video",
            )
            await increment_generated_videos(session=session, tg_id=tg_id, delta=1, section=mode)
            return {"assets": assets, "mode_id": mode, "kind": "video"}
        except Exception as exc:
            await refund_video_generation(session, tg_id, model_key=MODEL_PRICE_KLING_MOTION_KEY)
            raise WebGenerationError("Не удалось выполнить motion control.") from exc

    model = get_video_model(mode)
    if model is None:
        raise WebGenerationError(f"Неизвестный video mode: {mode}")

    duration = int(fields.get("duration") or model.duration_options[0])
    resolution = str(fields.get("resolution") or model.resolution_options[0].value)
    sound_enabled = _as_bool(fields.get("sound"))
    provider_cost_per_second = model.provider_cost_per_second(
        resolution=resolution,
        sound_enabled=sound_enabled,
    )
    credits_per_second = await get_scaled_model_price_credits(
        session,
        model.pricing_model_key,
        provider_cost_per_second,
    )
    total_credits = max(1, int(credits_per_second) * duration)

    try:
        await charge_video_generation(
            session,
            tg_id,
            model_key=model.pricing_model_key,
            credits_override=total_credits,
        )
    except NoGenerationsLeft as exc:
        raise WebGenerationError("Недостаточно кредитов для выбранной видео-модели.") from exc

    try:
        wavespeed = WaveSpeedClient(api_key=get_wavespeed_api_key_from_env())
        start_name, start_bytes = uploads[0]
        start_url = await wavespeed.upload_image_bytes(
            data=start_bytes,
            filename=start_name or "start.jpg",
            upload_path=f"wearai/video/{tg_id}",
        )
        payload: dict[str, object] = {
            "prompt": str(fields.get("prompt") or ""),
            "image": start_url,
            "duration": duration,
            "enable_safety_checker": True,
            "enable_sync_mode": False,
            "enable_base64_output": False,
        }
        if model.end_image_field and len(uploads) > 1:
            end_name, end_bytes = uploads[1]
            end_url = await wavespeed.upload_image_bytes(
                data=end_bytes,
                filename=end_name or "end.jpg",
                upload_path=f"wearai/video/{tg_id}",
            )
            payload[model.end_image_field] = end_url
        if model.supports_resolution:
            payload["resolution"] = resolution
        if model.aspect_ratio_options:
            payload["aspect_ratio"] = str(
                fields.get("aspect_ratio") or model.aspect_ratio_options[0]
            )
        if model.supports_negative_prompt:
            payload["negative_prompt"] = str(fields.get("negative_prompt") or "")
        if model.supports_sound:
            payload["sound"] = sound_enabled
        if model.supports_generate_audio:
            payload["generate_audio"] = _as_bool(fields.get("generate_audio"), default=True)
        if model.supports_web_search:
            payload["enable_web_search"] = _as_bool(fields.get("enable_web_search"))
        if model.supports_cfg_scale:
            payload["cfg_scale"] = float(fields.get("cfg_scale") or model.cfg_scale_options[0])
        if model.supports_shot_type:
            payload["shot_type"] = str(fields.get("shot_type") or model.shot_type_options[0])
        if model.supports_seed:
            payload["seed"] = int(fields.get("seed") if fields.get("seed") not in (None, "") else -1)

        task_id = await wavespeed.create_video_prediction_task(
            endpoint=model.endpoint,
            body=payload,
        )
        result_urls = await wavespeed.wait_result_urls(task_id, max_wait_s=30 * 60)
        if not result_urls:
            raise WebGenerationError("Видео-результат не найден.")
        video_url = result_urls[0]
        video_bytes = await wavespeed.download_bytes(video_url)
        out_name = _infer_filename(video_url, fallback=f"{mode}.mp4")
        assets = _save_binary_result(
            data=video_bytes,
            filename=out_name,
            scenario=mode,
            tg_id=tg_id,
            kind="video",
        )
        await increment_generated_videos(
            session=session,
            tg_id=tg_id,
            delta=1,
            section=f"video_{mode}",
        )
        return {"assets": assets, "mode_id": mode, "kind": "video"}
    except Exception as exc:
        await refund_video_generation(session, tg_id, model_key=model.pricing_model_key)
        raise WebGenerationError("Не удалось завершить видео-генерацию.") from exc


async def generate_music_mode(
    session: AsyncSession,
    *,
    client_id: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    user = await ensure_web_user(session, client_id=client_id)
    tg_id = user.tg_id
    selected_tags = list(fields.get("selected_tags") or [])
    sections = list(fields.get("sections") or [])
    section_texts = dict(fields.get("section_texts") or {})
    instrumental = bool(fields.get("instrumental"))
    duration = int(fields.get("duration") or 30)
    seed = int(fields.get("seed") or DEFAULT_SEED)
    labels = _selected_tag_labels(selected_tags)
    tags = ", ".join(labels)
    lyrics = compile_song_lyrics(
        sections=[{"key": f"section_{idx}", "type": item, "label": SECTION_LABELS.get(item, item.title())} for idx, item in enumerate(sections, start=1)],
        section_texts=section_texts,
        instrumental=instrumental,
    )
    credits_per_second = await get_model_price_credits(session, MODEL_PRICE_ACE_STEP_KEY)
    total_credits = max(1, credits_per_second * duration)

    try:
        await charge_video_generation(
            session,
            tg_id,
            model_key=MODEL_PRICE_ACE_STEP_KEY,
            credits_override=total_credits,
        )
    except NoGenerationsLeft as exc:
        raise WebGenerationError("Недостаточно кредитов для генерации музыки.") from exc

    try:
        client = WaveSpeedAceStepClient()
        task_id = await client.create_ace_step_task(
            tags=tags,
            lyrics=lyrics,
            duration=duration,
            seed=seed,
        )
        audio_url = await client.wait_audio_url(task_id)
        filename, audio_bytes = await client.download_audio_bytes(audio_url)
        assets = _save_binary_result(
            data=audio_bytes,
            filename=filename,
            scenario="music_ace_step",
            tg_id=tg_id,
            kind="audio",
        )
        from app.repository.users import increment_generated_music

        await increment_generated_music(
            session=session,
            tg_id=tg_id,
            delta=1,
            section="music_ace_step",
        )
        return {
            "assets": assets,
            "mode_id": "music_ace_step",
            "kind": "audio",
            "meta": {
                "tags": labels,
                "duration": duration,
                "sections": sections,
            },
        }
    except Exception as exc:
        await refund_video_generation(session, tg_id, model_key=MODEL_PRICE_ACE_STEP_KEY)
        raise WebGenerationError("Не удалось сгенерировать трек.") from exc


async def store_agent_document_for_web(
    session: AsyncSession,
    *,
    client_id: str,
    file_name: str | None,
    mime_type: str | None,
    data: bytes,
) -> dict[str, Any]:
    user = await ensure_web_user(session, client_id=client_id)
    settings = await ensure_agent_settings(session, user.id)
    extracted = extract_document_text(
        data,
        file_name=file_name,
        mime_type=mime_type,
    )
    doc = await add_agent_document(
        session,
        user_id=user.id,
        session_key=settings.document_session_key,
        telegram_file_id=f"web:{file_name or 'document'}",
        file_name=file_name,
        mime_type=mime_type,
        extracted_text=extracted,
    )
    return {
        "id": doc.id,
        "file_name": doc.file_name,
        "mime_type": doc.mime_type,
        "text_length": int(doc.text_length or 0),
    }


async def chat_with_agent_for_web(
    session: AsyncSession,
    *,
    client_id: str,
    user_text: str,
    toggles: dict[str, Any] | None = None,
) -> dict[str, Any]:
    user = await ensure_web_user(session, client_id=client_id)
    settings_row = await ensure_agent_settings(session, user.id)
    for field_name in (
        "web_search_enabled",
        "documents_enabled",
        "memory_enabled",
        "deep_analysis_enabled",
        "quick_mode_enabled",
    ):
        if toggles and field_name in toggles:
            setattr(settings_row, field_name, _as_bool(toggles.get(field_name)))
    await session.commit()
    await session.refresh(settings_row)

    requested_settings = snapshot_agent_settings(settings_row)
    pricing = await get_agent_request_pricing(session)
    requested_breakdown = build_agent_price_breakdown(
        pricing,
        memory_enabled=bool(requested_settings.memory_enabled),
        documents_enabled=bool(requested_settings.documents_enabled),
        web_search_enabled=bool(requested_settings.web_search_enabled),
        deep_analysis_enabled=bool(requested_settings.deep_analysis_enabled),
        quick_mode_enabled=bool(requested_settings.quick_mode_enabled),
    )

    try:
        charge = await charge_agent_request(
            session,
            user.tg_id,
            credits_override=int(requested_breakdown.total),
            prefer_paid=int(requested_breakdown.total) > int(requested_breakdown.base),
        )
    except NoGenerationsLeft as exc:
        raise WebGenerationError("Недостаточно кредитов для запроса к агенту.") from exc

    effective_settings = _effective_agent_settings(
        requested_settings,
        is_daily_free=charge.source == CHARGE_SOURCE_DAILY_FREE,
    )

    try:
        history = []
        if effective_settings.memory_enabled:
            history = await list_recent_agent_messages(
                session,
                user_id=user.id,
                limit=16,
            )

        documents = []
        if effective_settings.documents_enabled:
            documents = await list_agent_documents(
                session,
                user_id=user.id,
                session_key=settings_row.document_session_key,
                limit=20,
            )

        search_results = []
        if effective_settings.web_search_enabled:
            search_results = await search_web(
                user_text,
                quick_mode=effective_settings.quick_mode_enabled,
            )

        reply = await generate_agent_reply_streaming(
            user_text,
            settings=effective_settings,
            history=history,
            documents=documents,
            search_results=search_results,
        )
        await finalize_agent_request(session, user.tg_id)
        await add_agent_message(session, user_id=user.id, role="user", content=user_text)
        await add_agent_message(session, user_id=user.id, role="assistant", content=reply)
        return {
            "reply": reply,
            "charge": {
                "source": charge.source,
                "amount": int(charge.amount or 0),
            },
            "effective_settings": {
                "web_search_enabled": bool(effective_settings.web_search_enabled),
                "documents_enabled": bool(effective_settings.documents_enabled),
                "memory_enabled": bool(effective_settings.memory_enabled),
                "deep_analysis_enabled": bool(effective_settings.deep_analysis_enabled),
                "quick_mode_enabled": bool(effective_settings.quick_mode_enabled),
            },
        }
    except Exception as exc:
        await refund_agent_request(session, user.tg_id)
        raise WebGenerationError("Не удалось получить ответ от агента.") from exc
