from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.keyboards.menu import MenuCallbacks, main_menu_kb, photo_menu_kb, video_menu_kb
from app.utils.tg_edit import edit_text_safe

router = Router()


@router.callback_query(F.data == MenuCallbacks.PHOTO)
async def open_photo_menu(call: CallbackQuery) -> None:
    await edit_text_safe(
        call,
        "Выбери, что сделать с фото 👇",
        reply_markup=photo_menu_kb(),
    )
    await call.answer()


@router.callback_query(F.data == MenuCallbacks.VIDEO)
async def open_video_menu(call: CallbackQuery) -> None:
    await edit_text_safe(
        call,
        "Выбери, что сделать с видео 👇",
        reply_markup=video_menu_kb(),
    )
    await call.answer()


@router.callback_query(F.data == MenuCallbacks.BACK)
async def back_to_main_menu(call: CallbackQuery) -> None:
    await edit_text_safe(call, "Выбирай режим ниже 👇✨", reply_markup=main_menu_kb())
    await call.answer()
