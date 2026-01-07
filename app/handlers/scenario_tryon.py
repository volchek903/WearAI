from __future__ import annotations

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InputMediaPhoto
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.menu import MenuCallbacks
from app.keyboards.body_parts import body_parts_kb
from app.keyboards.confirm import yes_no_tryon_kb, ConfirmCallbacks
from app.keyboards.help import help_button_kb
from app.repository.users import increment_generated_photos, upsert_user
from app.states.tryon_flow import TryOnFlow
from app.utils.tg_edit import edit_text_safe

router = Router()


@router.callback_query(F.data == MenuCallbacks.TRYON)
async def start_tryon_flow(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await upsert_user(session, call.from_user.id, call.from_user.username)

    await state.clear()
    await state.set_state(TryOnFlow.user_photo)

    await edit_text_safe(
        call,
        "Поехали! 👕✨\n\nПришли свою фотографию (1 фото) 🤳",
        reply_markup=help_button_kb("user_photo", text="🤳 Как лучше сделать фото?"),
    )
    await call.answer()


@router.message(TryOnFlow.user_photo)
async def user_photo_in(message: Message, state: FSMContext) -> None:
    if message.media_group_id:
        await message.answer("Пожалуйста, пришли одну фотографию (не альбом) 🤳🙂")
        return

    if not message.photo:
        await message.answer(
            "Мне нужна именно фотография 🤳🙂 Пришли, пожалуйста, 1 фото."
        )
        return

    user_file_id = message.photo[-1].file_id
    await state.update_data(user_photo=user_file_id)
    await state.set_state(TryOnFlow.body_part)

    await message.answer(
        "Фото получил! ✅😊\n\nНа какую часть тела хочешь надеть одежду? 🎯",
        reply_markup=body_parts_kb(),
    )


@router.callback_query(TryOnFlow.body_part, F.data.startswith("body:"))
async def body_part_selected(call: CallbackQuery, state: FSMContext) -> None:
    body_part = call.data.split(":", 1)[1].strip()
    await state.update_data(body_part=body_part)
    await state.set_state(TryOnFlow.item_photo)

    await edit_text_safe(
        call,
        "Отлично! Теперь пришли фото вещи (1 фото) 📦📸",
        reply_markup=help_button_kb("item_photo", text="📦 Как лучше сфоткать вещь?"),
    )
    await call.answer()


@router.message(TryOnFlow.item_photo)
async def item_photo_in(message: Message, state: FSMContext) -> None:
    if message.media_group_id:
        await message.answer("Пожалуйста, пришли одно фото вещи (не альбом) 📸🙂")
        return

    if not message.photo:
        await message.answer("Хочу именно фото вещи 📸🙂 Пришли, пожалуйста, 1 фото.")
        return

    item_file_id = message.photo[-1].file_id
    data = await state.get_data()
    user_file_id = data.get("user_photo")

    if not user_file_id:
        await state.clear()
        await message.answer("Ой 😅 Сессия сбилась. Нажми /start и начни заново 🙌")
        return

    await state.update_data(item_photo=item_file_id)
    await state.set_state(TryOnFlow.confirm)

    media = [
        InputMediaPhoto(
            media=user_file_id,
            caption="Смотри 😊\nЭто твоё фото и вещь. Точно надеваем именно её? ✅",
        ),
        InputMediaPhoto(media=item_file_id),
    ]

    try:
        await message.answer_media_group(media=media)
    except Exception:
        await message.answer_photo(user_file_id, caption="Твоё фото 🤳")
        await message.answer_photo(item_file_id, caption="Фото вещи 📦")
        await message.answer("Точно надеваем именно эту вещь? ✅🙂")

    await message.answer("Жду твоё решение 👇🙂", reply_markup=yes_no_tryon_kb())


@router.callback_query(TryOnFlow.confirm, F.data == ConfirmCallbacks.NO)
async def tryon_choose_other(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(item_photo=None)
    await state.set_state(TryOnFlow.item_photo)

    await edit_text_safe(call, "Ок! 😄 Пришли другое фото вещи (1 фото) 📸")
    await call.answer()


@router.callback_query(TryOnFlow.confirm, F.data == ConfirmCallbacks.YES)
async def tryon_confirmed(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await upsert_user(session, call.from_user.id, call.from_user.username)

    await increment_generated_photos(session=session, tg_id=call.from_user.id, delta=1)
    await state.clear()

    await edit_text_safe(call, "ХОРОШО ✅😊")
    await call.answer()
