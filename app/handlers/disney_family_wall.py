from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InputMediaPhoto, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.confirm import ConfirmCallbacks, yes_no_kb
from app.keyboards.extra import buy_generations_kb
from app.keyboards.menu import MenuCallbacks, photo_two_kb
from app.repository.generations import (
    NoGenerationsLeft,
    charge_photo_generation,
    ensure_default_subscription,
    is_launch_subscription,
    refund_photo_generation,
)
from app.repository.users import increment_generated_photos, upsert_user
from app.services.album_collector import AlbumCollector
from app.services.generation import generate_image_wavespeed_from_telegram
from app.services.wavespeed_ai import WaveSpeedError
from app.states.disney_family_wall_flow import DisneyFamilyWallFlow
from app.utils.content_media import send_content_photo
from app.utils.launch_guard import block_launch_for_call
from app.utils.progress_bar import progress_initial_text, progress_loop, stop_progress
from app.utils.support_text import launch_limits_message, with_support
from app.utils.tg_callback import safe_answer
from app.utils.tg_edit import edit_text_safe
from app.utils.tg_send import send_image_smart
from app.utils.wavespeed_errors import wavespeed_error_to_user_text

router = Router()
logger = logging.getLogger(__name__)
_album = AlbumCollector(debounce_seconds=0.8)
_MAX_INPUT_PHOTOS = 8


def _build_prompt(ref_count: int) -> str:
    return (
        "Создайте качественную 3D-стилизованную мультяшную иллюстрацию по загруженным "
        "эталонным фото, где люди игриво подглядывают из-за вертикальной матовой стены "
        "слева. Видимы головы, руки и верхние части торса, расположенные вертикально "
        "друг под другом в чистой выровненной линии.\n\n"
        "Композиция: мягкая фактурная пастель, небесно-голубая стена на переднем плане "
        "слева и гладкий студийный градиентный фон в небесно-голубом тоне справа. "
        "Стиль: премиальный Pixar/Disney CGI, большие выразительные глаза, мягкая "
        "гладкая кожа, тонкий румянец, слегка увеличенные пропорции головы, "
        "кинематографичное ощущение, сохранение узнаваемых черт лиц, причесок и возраста "
        "по референсам. Все персонажи держат стену руками и слегка наклоняются вперед "
        "с любопытным игривым выражением. Освещение мягкое студийное, теплые нежные "
        "подсветки, без резких теней. Материалы: бархатистая матовая стена, мягкая ткань, "
        "гладкая кожа. Вертикальный портрет, центрированное кадрирование, неглубокая "
        "глубина резкости. Финальный рендер ультрачистый 4K, Octane/Unreal/Disney CGI.\n\n"
        "КРИТИЧЕСКОЕ ТРЕБОВАНИЕ: используй все загруженные референсы "
        f"({ref_count} шт.) и включи каждого человека из фотографий в итоговую сцену. "
        "Все люди с фото должны выглядывать из-за стены, никого не пропускай, "
        "не объединяй лица и не заменяй персонажей. "
        "Если на референсах есть домашние животные (кошка, собака и т.д.), "
        "тоже обязательно включи их в итоговую сцену: они должны выглядывать "
        "из-за стены вместе с людьми, с сохранением узнаваемого вида."
    )


async def _update_progress_message(msg: Message, text: str) -> None:
    try:
        await msg.edit_text(text)
    except Exception:
        return


@router.callback_query(F.data == MenuCallbacks.DISNEY_FAMILY_WALL)
async def start_disney_family_wall(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await safe_answer(call)
    await upsert_user(session, call.from_user.id, call.from_user.username)
    if await block_launch_for_call(call, session, reply_markup=buy_generations_kb()):
        return

    await state.clear()
    await state.set_state(DisneyFamilyWallFlow.photos)
    if call.message:
        try:
            await call.message.delete()
        except Exception:
            pass
        await send_content_photo(
            call.message,
            filename="disney_stena.jpeg",
            caption=(
                "🧱 <b>Семья выглядывает из-за стены</b>\n\n"
                "Пришли 1–8 фото семьи или влюблённых "
                "(одним сообщением или альбомом) 📸"
            ),
            parse_mode="HTML",
        )


@router.message(DisneyFamilyWallFlow.photos)
async def disney_family_wall_photos_in(message: Message, state: FSMContext) -> None:
    if not message.photo:
        await message.answer("Нужны фото 📸 Пришли от 1 до 8 изображений.")
        return

    if not message.media_group_id:
        file_id = message.photo[-1].file_id
        await state.update_data(photos=[file_id])
        await state.set_state(DisneyFamilyWallFlow.confirm)
        await message.answer_photo(
            file_id,
            caption="Проверь фото. Всё верно?",
            reply_markup=yes_no_kb(
                yes_text="✅ Всё верно",
                no_text="🔁 Отправить заново",
                no_style="danger",
            ),
        )
        return

    await _album.push(message.chat.id, message.media_group_id, message.photo[-1].file_id)
    result = await _album.collect(message.chat.id, message.media_group_id)
    if not result.file_ids:
        return

    if not (1 <= len(result.file_ids) <= _MAX_INPUT_PHOTOS):
        await message.answer(
            f"Нужно от 1 до {_MAX_INPUT_PHOTOS} фото одним сообщением (альбомом)."
        )
        return

    await state.update_data(photos=result.file_ids)
    await state.set_state(DisneyFamilyWallFlow.confirm)

    if len(result.file_ids) == 1:
        await message.answer_photo(
            result.file_ids[0],
            caption="Проверь фото. Всё верно?",
            reply_markup=yes_no_kb(
                yes_text="✅ Всё верно",
                no_text="🔁 Отправить заново",
                no_style="danger",
            ),
        )
        return

    media = [InputMediaPhoto(media=fid) for fid in result.file_ids]
    await message.answer_media_group(media=media)
    await message.answer(
        f"Получил {len(result.file_ids)} фото. Всё верно?",
        reply_markup=yes_no_kb(
            yes_text="✅ Всё верно",
            no_text="🔁 Отправить заново",
            no_style="danger",
        ),
    )


@router.callback_query(DisneyFamilyWallFlow.confirm, F.data == ConfirmCallbacks.NO)
async def disney_family_wall_confirm_no(
    call: CallbackQuery, state: FSMContext
) -> None:
    await state.update_data(photos=[])
    await state.set_state(DisneyFamilyWallFlow.photos)
    await edit_text_safe(
        call,
        "Ок, пришли 1–8 фото заново 📸",
        reply_markup=None,
    )
    await safe_answer(call)


@router.callback_query(DisneyFamilyWallFlow.confirm, F.data == ConfirmCallbacks.YES)
async def disney_family_wall_confirm_yes(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    photos: list[str] = list(data.get("photos") or [])
    if not photos:
        await state.clear()
        await safe_answer(call, "Фото не найдены 😕", show_alert=True)
        return

    photos = photos[:_MAX_INPUT_PHOTOS]
    if call.message is None:
        await safe_answer(call)
        return

    progress_msg = await call.message.answer(progress_initial_text())
    stop = asyncio.Event()
    progress_task = asyncio.create_task(
        progress_loop(lambda t: _update_progress_message(progress_msg, t), stop)
    )

    user = await upsert_user(session, call.from_user.id, call.from_user.username)
    tg_id = user.tg_id
    await ensure_default_subscription(session, tg_id)

    try:
        await charge_photo_generation(session, tg_id)
    except NoGenerationsLeft:
        await stop_progress(stop, progress_task)
        if await is_launch_subscription(session, tg_id):
            await edit_text_safe(
                progress_msg,
                launch_limits_message(),
                reply_markup=buy_generations_kb(),
            )
        else:
            await edit_text_safe(
                progress_msg,
                "⛔️ Недостаточно кредитов.\n\nПополните баланс 💳",
                reply_markup=buy_generations_kb(),
            )
        await state.clear()
        await safe_answer(call)
        return

    sent_any = False
    try:
        results = await generate_image_wavespeed_from_telegram(
            bot=call.bot,
            session=session,
            tg_id=tg_id,
            prompt=_build_prompt(len(photos)),
            telegram_photo_file_ids=photos,
            aspect_ratio="9:16",
            max_images=_MAX_INPUT_PHOTOS,
        )
        if not results:
            raise RuntimeError("WaveSpeed returned empty result")

        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, "✅ Готово! Отправляю результат…")

        for filename, img_bytes in results:
            await send_image_smart(call.message, img_bytes=img_bytes, filename=filename)
            sent_any = True

        await increment_generated_photos(
            session=session, tg_id=tg_id, delta=1, section="disney_family_wall"
        )
        await state.clear()
        await call.message.answer(
            "Хотите ли что-то ещё сгенерировать?",
            reply_markup=photo_two_kb(),
        )
        await safe_answer(call)
    except WaveSpeedError as e:
        logger.exception("disney_family_wall: wavespeed error user=%s", tg_id)
        await refund_photo_generation(session, tg_id)
        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, wavespeed_error_to_user_text(e))
        await state.clear()
        await safe_answer(call)
    except Exception as e:
        logger.exception("disney_family_wall: generation failed user=%s", tg_id)
        if not sent_any:
            await refund_photo_generation(session, tg_id)
        await stop_progress(stop, progress_task)
        await edit_text_safe(
            progress_msg,
            with_support(f"Не удалось сгенерировать изображение: {e}"),
            reply_markup=buy_generations_kb() if not sent_any else None,
        )
        await state.clear()
        await safe_answer(call)
