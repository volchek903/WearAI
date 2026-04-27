from __future__ import annotations

import logging

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import CallbackQuery, Message

from app.keyboards.menu import main_menu_kb
from app.utils.tg_edit import edit_text_safe
from app.utils.support_text import with_support

router = Router()
logger = logging.getLogger(__name__)


@router.error()
async def global_error_handler(event, exception: Exception | None = None, **kwargs):
    if isinstance(exception, TelegramRetryAfter):
        retry_after = float(getattr(exception, "retry_after", 0) or 0)
        logger.warning(
            "global_error_handler: suppressed TelegramRetryAfter retry_after=%ss",
            retry_after,
        )
        return True

    try:
        update = getattr(event, "update", None)
        if update and getattr(update, "callback_query", None):
            call: CallbackQuery = update.callback_query
            await edit_text_safe(
                call,
                with_support(
                    "Что‑то пошло не так 😔\n"
                    "Сообщите о поломке нам и получите подарок за бдительность:\n"
                    "@WearAIManager"
                ),
                reply_markup=main_menu_kb(),
            )
            try:
                await call.answer()
            except (TelegramBadRequest, TelegramRetryAfter):
                pass
            return True
        if update and getattr(update, "message", None):
            msg: Message = update.message
            await msg.answer(
                with_support(
                    "Что‑то пошло не так 😔\n"
                    "Сообщите о поломке нам и получите подарок за бдительность:\n"
                    "@WearAIManager"
                ),
                reply_markup=main_menu_kb(),
            )
            return True
    except TelegramRetryAfter as e:
        logger.warning(
            "global_error_handler: reply hit TelegramRetryAfter retry_after=%ss",
            float(getattr(e, "retry_after", 0) or 0),
        )
    except Exception:
        logger.exception("global_error_handler failed")
    return True
