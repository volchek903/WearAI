from __future__ import annotations

import asyncio
import logging
from io import BytesIO
import time
import uuid

import aiohttp

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InputMediaPhoto, Message, BufferedInputFile
from sqlalchemy.ext.asyncio import AsyncSession
from PIL import Image

from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.keyboards.menu import MenuCallbacks, photo_menu_kb
from app.keyboards.extra import buy_generations_kb
from app.keyboards.love_is import LoveIsCallbacks, love_is_post_kb
from app.keyboards.utils import add_button
from app.repository.generations import (
    NoGenerationsLeft,
    charge_photo_generation,
    charge_video_generation,
    ensure_default_subscription,
    refund_photo_generation,
    refund_video_generation,
)
from app.repository.users import (
    increment_generated_photos,
    increment_generated_videos,
    upsert_user,
)
from app.services.album_collector import AlbumCollector
from app.services.generation import generate_image_kie_from_telegram
from app.states.love_is_flow import LoveIsFlow
from app.utils.tg_edit import edit_text_safe
from app.utils.content_media import send_content_photo
from app.utils.tg_send import send_image_smart
from app.utils.support_text import with_support
from app.utils.progress_bar import (
    progress_initial_text,
    progress_loop,
    stop_progress,
)
from app.utils.generated_files import save_generated_image_bytes
from app.utils.kie_kling_client import KieKlingClient
from app.db.config import settings

router = Router()
logger = logging.getLogger(__name__)

_album = AlbumCollector(debounce_seconds=0.8)
_MAX_BYTES = 10 * 1024 * 1024


@router.callback_query(F.data == MenuCallbacks.LOVE_IS)
async def love_is_start(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.clear()
    await state.set_state(LoveIsFlow.photos)
    if call.message:
        try:
            await call.message.delete()
        except Exception:
            pass
        await send_content_photo(
            call.message,
            filename="love_is.jpeg",
            caption=(
                "❤️ <b>ИИ Love is</b>\n\n"
                "Пришли 1–2 фото (лучше: мужчина и женщина) одним сообщением или альбомом 📸"
            ),
            parse_mode="HTML",
        )


def _back_only_kb():
    kb = InlineKeyboardBuilder()
    add_button(kb, text="⬅️ В меню", callback_data=MenuCallbacks.BACK, style="danger")
    kb.adjust(1)
    return kb.as_markup()


@router.message(LoveIsFlow.photos)
async def love_is_photos_in(message: Message, state: FSMContext) -> None:
    if not message.photo:
        await message.answer("Нужны фото 📸 Пришли 1–2 изображения.")
        return

    if not message.media_group_id:
        file_id = message.photo[-1].file_id
        await state.update_data(photos=[file_id])
        await state.set_state(LoveIsFlow.text)
        await message.answer("Теперь напиши текст, который будет под фото ✍️")
        return

    await _album.push(
        message.chat.id, message.media_group_id, message.photo[-1].file_id
    )
    result = await _album.collect(message.chat.id, message.media_group_id)

    if not result.file_ids:
        return

    if not (1 <= len(result.file_ids) <= 2):
        await message.answer("Нужно 1–2 фото одним сообщением. Попробуй ещё раз 🙌")
        return

    await state.update_data(photos=result.file_ids)
    await state.set_state(LoveIsFlow.text)
    await message.answer("Теперь напиши текст, который будет под фото ✍️")


@router.message(LoveIsFlow.text)
async def love_is_text_in(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Нужен текст ✍️ Напиши, что должно быть под фото.")
        return

    data = await state.get_data()
    photos = data.get("photos") or []
    if not photos:
        await state.clear()
        await message.answer("Не нашёл фото в сессии. Начни заново 🙌")
        return

    tg_id = message.from_user.id

    await upsert_user(session, tg_id, message.from_user.username)
    await ensure_default_subscription(session, tg_id)
    try:
        await charge_photo_generation(session, tg_id)
    except NoGenerationsLeft:
        await message.answer(
            "⛔️ Лимит генераций исчерпан.\n\nОформи подписку или пополни баланс 💳",
            reply_markup=buy_generations_kb(),
        )
        await state.clear()
        return

    progress_msg = await message.answer(progress_initial_text())
    stop = asyncio.Event()

    async def _update(text: str) -> None:
        try:
            await progress_msg.edit_text(text)
        except Exception:
            return

    progress_task = asyncio.create_task(progress_loop(_update, stop))

    sent_any = False
    try:
        prompt = (
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
            "детализированный, не отвлекающий (улица, машина, куртки, городской или "
            "зимний антураж — адаптирован по исходному фото). В верхней части "
            "открытки крупная надпись: “Love is…” шрифт — рукописный, мультяшный, "
            "чёрного цвета с маленьким сердечком. В нижней части открытки — подпись "
            f"в стиле Love is: “{text}” Иллюстрация выглядит как готовая "
            "печатная открытка ко Дню святого Валентина, высокое качество, "
            "чистый белый фон, мягкий свет, лёгкая романтическая атмосфера, "
            "чувство любви, нежности и уюта. Стиль: романтическая иллюстрация, "
            "cartoon illustration, love is style, valentine postcard, hand-drawn, "
            "soft shading, clean lineart, cute couple."
        )
        results = await generate_image_kie_from_telegram(
            bot=message.bot,
            session=session,
            tg_id=tg_id,
            prompt=prompt,
            telegram_photo_file_ids=photos,
            aspect_ratio="3:4",
        )
        if not results:
            raise RuntimeError("KIE returned empty result")

        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, "✅ Готово! Отправляю результат…")

        first_path = ""
        for filename, img_bytes in results:
            local_path = save_generated_image_bytes(
                img_bytes=img_bytes,
                filename=filename,
                scenario="love_is",
                tg_id=tg_id,
            )
            if not first_path:
                first_path = local_path
            await send_image_smart(message, img_bytes=img_bytes, filename=filename)
            sent_any = True

        await increment_generated_photos(session=session, tg_id=tg_id, delta=1)

        if first_path:
            await state.update_data(love_is_image_path=first_path)
            await state.set_state(LoveIsFlow.ready)
            await message.answer(
                "Готово! Хочешь оживить открытку? 🎬",
                reply_markup=love_is_post_kb(),
            )
            await message.answer(
                "Хотите ли что-то ещё сгенерировать?",
                reply_markup=photo_menu_kb(),
            )

    except Exception as e:
        logger.exception("LOVE_IS generation failed: %s", e)
        if not sent_any:
            await refund_photo_generation(session, tg_id)
        await stop_progress(stop, progress_task)
        await message.answer(
            with_support("Не получилось сгенерировать 😅 Попробуй ещё раз чуть позже.")
        )
    finally:
        if await state.get_state() != LoveIsFlow.ready.state:
            await state.clear()


def _compress_to_limit(data: bytes, max_bytes: int = _MAX_BYTES) -> bytes:
    if len(data) <= max_bytes:
        return data

    img = Image.open(BytesIO(data))
    img = img.convert("RGB")

    quality = 90
    scale = 1.0
    while True:
        buf = BytesIO()
        w, h = img.size
        if scale < 1.0:
            img_resized = img.resize(
                (int(w * scale), int(h * scale)), Image.LANCZOS
            )
        else:
            img_resized = img

        img_resized.save(buf, format="JPEG", quality=quality, optimize=True)
        out = buf.getvalue()
        if len(out) <= max_bytes:
            return out

        if quality > 40:
            quality -= 10
        else:
            scale *= 0.9
            if scale < 0.5:
                return out


@router.callback_query(LoveIsFlow.ready, F.data == LoveIsCallbacks.ANIMATE)
async def love_is_animate(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await call.answer()
    data = await state.get_data()
    path = data.get("love_is_image_path") or ""
    if not path:
        await call.message.answer("Не нашёл открытку. Сгенерируй её заново 🙌")
        await state.clear()
        return

    if not settings.kie_api_key:
        await call.message.answer("Не настроен KIE_API_KEY в .env 😕")
        return

    tg_id = call.from_user.id
    await ensure_default_subscription(session, tg_id)

    try:
        await charge_video_generation(session, tg_id)
    except NoGenerationsLeft:
        await call.message.answer(
            "⛔️ Лимит генераций видео исчерпан.\n\nОформи подписку или пополни баланс 💳"
        )
        await state.clear()
        return

    try:
        with open(path, "rb") as f:
            img_bytes = f.read()
    except Exception:
        await call.message.answer("Не удалось открыть файл открытки 😕")
        await state.clear()
        return

    img_bytes = _compress_to_limit(img_bytes)
    if len(img_bytes) > _MAX_BYTES:
        await refund_video_generation(session, tg_id)
        await call.message.answer("Не удалось сжать файл до 10 МБ 😕")
        await state.clear()
        return

    client = KieKlingClient(settings.kie_api_key)
    progress_msg = await call.message.answer(progress_initial_text())
    stop = asyncio.Event()

    async def _update(text: str) -> None:
        try:
            await progress_msg.edit_text(text)
        except Exception:
            return

    progress_task = asyncio.create_task(progress_loop(_update, stop))

    try:

        tag = f"{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
        image_url = await client.upload_image_bytes(
            image_bytes=img_bytes,
            filename=f"love_is_{tg_id}_{tag}.jpg",
            upload_path=f"images/wearai/love_is/{tg_id}/{tag}",
        )

        task_id = await client.create_kling_task(
            prompt="gentle romantic motion, subtle smiles, soft movement",
            image_url=image_url,
            duration="5",
            negative_prompt="blur, distort, low quality, artifacts",
            cfg_scale=1.0,
        )

        res = await client.wait_for_success(
            task_id, poll_interval_s=10, max_wait_s=30 * 60
        )
        if res.state == "timeout":
            raise RuntimeError("timeout")
        if res.fail_msg:
            raise RuntimeError(res.fail_msg)
        if not res.result_url:
            raise RuntimeError("no result url")

        direct_url = await client.to_direct_download_url(res.result_url)
        video_bytes = await _download_bytes(direct_url)
        video_file = BufferedInputFile(video_bytes, filename="love_is.mp4")

        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, "✅ Готово! Отправляю видео…")

        await call.message.answer_video(
            video=video_file,
            caption="Готово! 💞",
            supports_streaming=True,
        )
        await increment_generated_videos(session=session, tg_id=tg_id, delta=1)
        await call.message.answer(
            "Хотите ли что-то ещё сгенерировать?",
            reply_markup=photo_menu_kb(),
        )
    except Exception as e:
        logger.exception("LOVE_IS animate failed: %s", e)
        await refund_video_generation(session, tg_id)
        await stop_progress(stop, progress_task)
        await call.message.answer(
            with_support("Не получилось оживить открытку 😅 Попробуй позже.")
        )
    finally:
        await state.clear()


async def _download_bytes(url: str, timeout_s: int = 240) -> bytes:
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout_s)
    ) as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.read()
