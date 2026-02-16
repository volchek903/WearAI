from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.keyboards.menu import (
    MenuCallbacks,
    main_menu_kb,
    photo_menu_kb,
    photo_cars_kb,
    photo_two_kb,
    photo_one_kb,
    video_menu_kb,
)
from app.utils.tg_edit import edit_text_safe

router = Router()


@router.callback_query(F.data == MenuCallbacks.PHOTO)
async def open_photo_menu(call: CallbackQuery) -> None:
    await edit_text_safe(
        call,
        "Выбери раздел для генерации фото 👇",
        reply_markup=photo_menu_kb(),
    )
    await call.answer()


@router.callback_query(F.data == MenuCallbacks.PHOTO_CARS)
async def open_photo_cars(call: CallbackQuery) -> None:
    await edit_text_safe(
        call,
        "🚗 Шаблоны с машинами — выбери модуль 👇",
        reply_markup=photo_cars_kb(),
    )
    await call.answer()


@router.callback_query(F.data == MenuCallbacks.PHOTO_TWO)
async def open_photo_two(call: CallbackQuery) -> None:
    await edit_text_safe(
        call,
        "👫 Шаблоны для двоих — выбери модуль 👇",
        reply_markup=photo_two_kb(),
    )
    await call.answer()


@router.callback_query(F.data == MenuCallbacks.PHOTO_ONE)
async def open_photo_one(call: CallbackQuery) -> None:
    await edit_text_safe(
        call,
        "🧍‍♂️ Шаблоны для одного — выбери модуль 👇",
        reply_markup=photo_one_kb(),
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
    await edit_text_safe(call, "Главное меню 👇", reply_markup=main_menu_kb())
    await call.answer()
