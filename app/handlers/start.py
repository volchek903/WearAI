from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.menu import main_menu_kb, MenuCallbacks
from app.keyboards.help import help_choose_kb
from app.repository.users import upsert_user
from app.repository.photo_settings import ensure_photo_settings
from app.utils.tg_edit import edit_text_safe

router = Router()


async def _hard_reset_user_runtime_caches(*, chat_id: int) -> None:
    """
    Best-effort очистка рантайм-кешей (FSM и временные буферы альбомов).
    Важно: здесь НЕ должно быть критичных импортов на уровне модуля, чтобы избежать циклов.
    """
    # AlbumCollector буферы (если используются)
    try:
        from app.handlers import (
            scenario_model,
        )  # локальный импорт, чтобы не словить циклы

        album = getattr(scenario_model, "_album", None)
        if album and hasattr(album, "clear_chat"):
            await album.clear_chat(chat_id)
    except Exception:
        # cache clean — best effort, не валим /start
        pass


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    # 1) Жёстко чистим FSM, чтобы не “прилипали” прошлые file_id/промпты/feedback_payload
    await state.clear()

    # 2) Best-effort чистим временные буферы (альбомы и т.п.)
    await _hard_reset_user_runtime_caches(chat_id=message.chat.id)

    # 3) Upsert пользователя и гарантируем наличие настроек в БД
    user = await upsert_user(
        session=session,
        tg_id=message.from_user.id,
        username=message.from_user.username,
    )
    await ensure_photo_settings(session=session, user_id=user.id)

    # 4) Стартовое сообщение + меню
    await message.answer(
        "Привет! Я WEARAI 👋\n\n"
        "Коротко что я умею:\n"
        "🛍 <b>Модель с товаром</b> — опиши модель, загрузи до 5 фото товара 📸 и напиши, как его показать.\n"
        "👕 <b>Примерить одежду</b> — пришли своё фото 🤳, выбери часть тела 🎯, пришли фото вещи 📦 и подтверди.\n\n"
        "Выбери режим ниже 👇",
        reply_markup=main_menu_kb(),
    )


@router.callback_query(F.data == MenuCallbacks.HELP)
async def menu_help(call: CallbackQuery) -> None:
    await edit_text_safe(
        call,
        "Конечно! 😊\n\nЧто будем генерировать? 👇",
        reply_markup=help_choose_kb(),
    )
    await call.answer()
