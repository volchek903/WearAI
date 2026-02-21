from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.extra import buy_generations_kb
from app.keyboards.menu import MenuCallbacks, photo_menu_kb
from app.keyboards.utils import add_button
from app.repository.generations import (
    NoGenerationsLeft,
    charge_photo_generation,
    ensure_default_subscription,
    refund_photo_generation,
    is_launch_subscription,
)
from app.repository.users import increment_generated_photos, upsert_user
from app.services.generation import generate_image_kie_from_telegram
from app.services.kie_ai import KieAIError
from app.states.car_in_hand_flow import CarInHandFlow
from app.utils.kie_errors import kie_error_to_user_text
from app.utils.progress_bar import progress_initial_text, progress_loop, stop_progress
from app.utils.tg_edit import edit_text_safe
from app.utils.content_media import send_content_album
from app.utils.tg_send import send_image_smart
from app.utils.support_text import with_support, launch_limits_message
from app.utils.tg_callback import safe_answer

router = Router()
logger = logging.getLogger(__name__)

HAND_OPTIONS = {
    "male_glove": "мужская рука в перчатке",
    "male_no_glove": "мужская рука без перчатки",
    "female_glove": "женская рука в перчатке",
    "female_no_glove": "женская рука без перчатки",
}


def _hand_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    add_button(kb, text="Мужская, в перчатке", callback_data="carhand:hand:male_glove")
    add_button(
        kb, text="Мужская, без перчатки", callback_data="carhand:hand:male_no_glove"
    )
    add_button(kb, text="Женская, в перчатке", callback_data="carhand:hand:female_glove")
    add_button(
        kb, text="Женская, без перчатки", callback_data="carhand:hand:female_no_glove"
    )
    kb.adjust(1)
    return kb


def _build_prompt(background: str, hand_desc: str) -> str:
    return (
        "Ультрареалистичное фото по реф. машины: мини-копия в руке 100% идентична оригиналу "
        "(бренд, модель, цвет, пропорции, детали).\n"
        f"{background}\n"
        "В кадре только дорога, рука и мини-машина.\n"
        f"Рука: {hand_desc}. Рука естественно держит мини-машину над дорогой, перспектива реалистичная.\n"
        "Крупный/средний план, малая ГРИП: рука и машина в фокусе, фон мягко размытый.\n"
        "Мягкий дневной зимний свет, холодные тона, реальные тени и отражения.\n"
        "Фотореализм, один кадр, без CGI, стилизации и изменений дизайна."
    )


async def _update_progress_message(msg: Message, text: str) -> None:
    try:
        await msg.edit_text(text)
    except Exception:
        return


@router.callback_query(F.data == MenuCallbacks.CAR_IN_HAND)
async def car_in_hand_start(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await call.answer()
    await upsert_user(session, call.from_user.id, call.from_user.username)
    await state.clear()
    await state.set_state(CarInHandFlow.photo)

    if call.message:
        try:
            await call.message.delete()
        except Exception:
            pass
        await send_content_album(
            call.message,
            filenames=["mini_car.jpg", "mini_car1.jpg"],
            caption="✋ <b>Ваша машина в руке</b>\n\nПришли фото машины 📸",
            parse_mode="HTML",
        )


@router.message(CarInHandFlow.photo)
async def car_in_hand_photo(message: Message, state: FSMContext) -> None:
    if not message.photo:
        await message.answer("Нужно фото машины 📸")
        return
    if message.media_group_id:
        await message.answer("Нужно одно фото (не альбом) 📸")
        return

    await state.update_data(photo_id=message.photo[-1].file_id)
    await state.set_state(CarInHandFlow.background)
    await message.answer(
        "Теперь опиши задний фон ✍️\n"
        "Пример: «Зимняя заснеженная лесная дорога»"
    )


@router.message(CarInHandFlow.background)
async def car_in_hand_background(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Нужно описание фона ✍️")
        return

    await state.update_data(background=text)
    await state.set_state(CarInHandFlow.hand)
    await message.answer("Выбери руку 👇", reply_markup=_hand_kb().as_markup())


@router.callback_query(CarInHandFlow.hand, F.data.startswith("carhand:hand:"))
async def car_in_hand_hand(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    key = (call.data or "").rsplit(":", 1)[-1].strip()
    hand_desc = HAND_OPTIONS.get(key)
    if not hand_desc:
        await call.answer("Некорректный выбор 😕", show_alert=True)
        return

    data = await state.get_data()
    photo_id = data.get("photo_id")
    background = data.get("background", "")
    if not photo_id:
        await state.clear()
        await call.answer("Не вижу фото 😕", show_alert=True)
        return

    prompt = _build_prompt(background, hand_desc)

    if call.message is None:
        await safe_answer(call)
        return

    await ensure_default_subscription(session, call.from_user.id)
    try:
        await charge_photo_generation(session, call.from_user.id)
    except NoGenerationsLeft:
        if await is_launch_subscription(session, call.from_user.id):
            await edit_text_safe(
                call, launch_limits_message(), reply_markup=buy_generations_kb()
            )
        else:
            await edit_text_safe(
                call,
                "⛔️ Лимит генераций исчерпан.\n\nОформи подписку или пополни баланс 💳",
                reply_markup=buy_generations_kb(),
            )
        await state.clear()
        await safe_answer(call)
        return

    progress_msg = await call.message.answer(progress_initial_text())
    stop = asyncio.Event()
    progress_task = asyncio.create_task(
        progress_loop(lambda t: _update_progress_message(progress_msg, t), stop)
    )

    sent_any = False
    try:
        results = await generate_image_kie_from_telegram(
            bot=call.bot,
            session=session,
            tg_id=call.from_user.id,
            prompt=prompt,
            telegram_photo_file_ids=[photo_id],
            max_images=1,
        )

        if not results:
            raise RuntimeError("KIE returned empty result")

        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, "✅ Готово! Отправляю результат…")

        for filename, img_bytes in results:
            await send_image_smart(call.message, img_bytes=img_bytes, filename=filename)
            sent_any = True

        await increment_generated_photos(session=session, tg_id=call.from_user.id, delta=1)
        await state.clear()
        await call.message.answer(
            "Хотите ли что-то ещё сгенерировать?",
            reply_markup=photo_menu_kb(),
        )
        await safe_answer(call)
        return

    except KieAIError as e:
        logger.warning("CAR_IN_HAND generation failed: %s", e)
        if not sent_any:
            await refund_photo_generation(session, call.from_user.id)
        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, kie_error_to_user_text(e))
        await state.clear()
        await safe_answer(call)
        return

    except Exception as e:
        logger.exception("CAR_IN_HAND generation failed: %s", e)
        if not sent_any:
            await refund_photo_generation(session, call.from_user.id)
        await stop_progress(stop, progress_task)
        await edit_text_safe(
            progress_msg,
            with_support(
                "Не получилось сгенерировать 😅\n"
                "Попробуй ещё раз или вернись в меню."
            ),
            reply_markup=photo_menu_kb(),
        )
        await state.clear()
        await call.answer()
        return
