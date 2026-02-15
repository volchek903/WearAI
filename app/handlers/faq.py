from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.keyboards.faq import FAQ_BACK_CB, faq_kb
from app.keyboards.menu import MenuCallbacks, main_menu_kb
from app.utils.content_media import send_content_photo
from app.utils.tg_edit import edit_text_safe

router = Router()


@router.callback_query(F.data == MenuCallbacks.FAQ)
async def faq_open(cb: CallbackQuery) -> None:
    if cb.message is None:
        await cb.answer()
        return

    text = (
        "❓ <b>FAQ</b>\n\n"
        "Выбери нужный раздел ниже 👇"
    )

    await edit_text_safe(cb, text, reply_markup=faq_kb())
    await cb.answer()


@router.callback_query(F.data == FAQ_BACK_CB)
async def faq_back(cb: CallbackQuery) -> None:
    if cb.message is None:
        await cb.answer()
        return

    await send_content_photo(
        cb.message,
        filename="welcome.png",
        caption="Главное меню 👇",
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
    )
    await cb.answer()
