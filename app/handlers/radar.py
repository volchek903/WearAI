from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.keyboards.menu import MenuCallbacks, photo_menu_kb
from app.utils.tg_edit import edit_text_safe

router = Router()


@router.callback_query(F.data == MenuCallbacks.RADAR)
async def radar_entry(call: CallbackQuery) -> None:
    await edit_text_safe(
        call,
        "🛰 <b>ИИ Радар</b>\n\nРаздел в разработке. Скоро будет доступен ✨",
        reply_markup=photo_menu_kb(),
    )
    await call.answer()
