from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import CallbackQuery, Message, Update

from app.keyboards.menu import main_menu_kb
from app.utils.tg_edit import edit_text_safe

router = Router()
logger = logging.getLogger(__name__)


@router.error()
async def global_error_handler(update: Update, exception: Exception):
    try:
        if update.callback_query:
            call: CallbackQuery = update.callback_query
            await edit_text_safe(
                call,
                "Что‑то пошло не так 😔\n"
                "Сообщите о поломке нам и получите подарок за бдительность:\n"
                "@WearAIManager",
                reply_markup=main_menu_kb(),
            )
            await call.answer()
            return True
        if update.message:
            msg: Message = update.message
            await msg.answer(
                "Что‑то пошло не так 😔\n"
                "Сообщите о поломке нам и получите подарок за бдительность:\n"
                "@WearAIManager",
                reply_markup=main_menu_kb(),
            )
            return True
    except Exception:
        logger.exception("global_error_handler failed")
    return True
