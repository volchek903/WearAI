from __future__ import annotations

import asyncio
import logging

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.admin import (
    AdminCallbacks,
    AdminBroadcastCallbacks,
    admin_broadcast_kb,
    admin_menu_kb,
)
from app.keyboards.confirm import ConfirmCallbacks, yes_no_kb
from app.repository.admin import get_all_user_tg_ids, is_admin
from app.repository.admin_actions import log_admin_action
from app.states.admin_broadcast import AdminBroadcastFSM
from app.utils.tg_edit import edit_text_safe

router = Router()
logger = logging.getLogger(__name__)


async def _ensure_admin(call_or_message, session: AsyncSession, action: str) -> bool:
    tg_id = getattr(call_or_message.from_user, "id", None)
    if tg_id is None:
        return False
    if await is_admin(session, tg_id):
        data = getattr(call_or_message, "data", None) or getattr(call_or_message, "text", None) or ""
        await log_admin_action(session, tg_id=tg_id, action=action, data=str(data))
        return True
    logger.warning(
        "ADMIN_DENY action=%s tg_id=%s data=%s",
        action,
        tg_id,
        getattr(call_or_message, "data", None),
    )
    if isinstance(call_or_message, CallbackQuery):
        await call_or_message.answer("Недостаточно прав", show_alert=True)
    elif isinstance(call_or_message, Message):
        await call_or_message.answer("Недостаточно прав")
    return False


def _type_prompt(kind: str) -> str:
    if kind == "photo":
        return "Пришли фото для рассылки."
    if kind == "photo_text":
        return "Пришли фото с подписью (текст в caption)."
    if kind == "video":
        return "Пришли видео для рассылки."
    if kind == "video_text":
        return "Пришли видео с подписью (текст в caption)."
    if kind == "voice":
        return "Пришли голосовое сообщение."
    if kind == "text":
        return "Напиши текст рассылки."
    return "Выбери формат рассылки."


async def _send_payload(bot, chat_id: int, payload: dict) -> None:
    kind = payload.get("kind")
    if kind == "text":
        await bot.send_message(chat_id, payload.get("text", ""))
        return
    if kind == "photo":
        await bot.send_photo(chat_id, payload["file_id"])
        return
    if kind == "photo_text":
        await bot.send_photo(
            chat_id, payload["file_id"], caption=payload.get("text", "")
        )
        return
    if kind == "video":
        await bot.send_video(chat_id, payload["file_id"])
        return
    if kind == "video_text":
        await bot.send_video(
            chat_id, payload["file_id"], caption=payload.get("text", "")
        )
        return
    if kind == "voice":
        await bot.send_voice(chat_id, payload["file_id"])
        return
    raise RuntimeError(f"Unknown broadcast kind: {kind}")


@router.callback_query(F.data == AdminCallbacks.BROADCAST)
async def broadcast_start(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    if not await _ensure_admin(call, session, "admin_broadcast.start"):
        return
    await state.clear()
    await state.set_state(AdminBroadcastFSM.choice)
    await edit_text_safe(
        call, "📣 Выбери формат рассылки:", reply_markup=admin_broadcast_kb()
    )
    await call.answer()


@router.callback_query(
    AdminBroadcastFSM.choice,
    F.data.in_(
        {
            AdminBroadcastCallbacks.PHOTO,
            AdminBroadcastCallbacks.PHOTO_TEXT,
            AdminBroadcastCallbacks.VIDEO,
            AdminBroadcastCallbacks.VIDEO_TEXT,
            AdminBroadcastCallbacks.VOICE,
            AdminBroadcastCallbacks.TEXT,
            AdminBroadcastCallbacks.BACK,
        }
    ),
)
async def broadcast_pick_type(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    if not await _ensure_admin(call, session, "admin_broadcast.pick_type"):
        return

    if call.data == AdminBroadcastCallbacks.BACK:
        await state.clear()
        await edit_text_safe(call, "⚙️ Админка", reply_markup=admin_menu_kb())
        await call.answer()
        return

    kind = call.data.replace("admin:broadcast:", "", 1)
    await state.update_data(kind=kind)
    await state.set_state(AdminBroadcastFSM.waiting_content)
    await edit_text_safe(call, _type_prompt(kind), reply_markup=None)
    await call.answer()


@router.message(AdminBroadcastFSM.waiting_content)
async def broadcast_receive_content(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    if not await _ensure_admin(message, session, "admin_broadcast.receive"):
        return

    data = await state.get_data()
    kind = data.get("kind")

    payload: dict | None = None

    if kind == "text":
        txt = (message.text or "").strip()
        if not txt:
            await message.answer("Нужен текст.")
            return
        payload = {"kind": "text", "text": txt}

    elif kind in {"photo", "photo_text"}:
        if not message.photo:
            await message.answer("Нужно фото.")
            return
        if kind == "photo_text":
            caption = (message.caption or "").strip()
            if not caption:
                await message.answer("Нужна подпись (текст) к фото.")
                return
            payload = {
                "kind": "photo_text",
                "file_id": message.photo[-1].file_id,
                "text": caption,
            }
        else:
            payload = {"kind": "photo", "file_id": message.photo[-1].file_id}

    elif kind in {"video", "video_text"}:
        if not message.video:
            await message.answer("Нужно видео.")
            return
        if kind == "video_text":
            caption = (message.caption or "").strip()
            if not caption:
                await message.answer("Нужна подпись (текст) к видео.")
                return
            payload = {
                "kind": "video_text",
                "file_id": message.video.file_id,
                "text": caption,
            }
        else:
            payload = {"kind": "video", "file_id": message.video.file_id}

    elif kind == "voice":
        if not message.voice:
            await message.answer("Нужно голосовое сообщение.")
            return
        payload = {"kind": "voice", "file_id": message.voice.file_id}

    else:
        await message.answer("Неизвестный формат. Начни заново.")
        await state.clear()
        return

    await state.update_data(payload=payload)
    await state.set_state(AdminBroadcastFSM.confirm)

    await _send_payload(message.bot, message.chat.id, payload)
    await message.answer(
        "Отправить это всем пользователям?", reply_markup=yes_no_kb()
    )


@router.callback_query(AdminBroadcastFSM.confirm, F.data == ConfirmCallbacks.NO)
async def broadcast_cancel(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    if not await _ensure_admin(call, session, "admin_broadcast.cancel"):
        return
    await state.clear()
    await edit_text_safe(call, "❌ Отменено", reply_markup=admin_menu_kb())
    await call.answer()


@router.callback_query(AdminBroadcastFSM.confirm, F.data == ConfirmCallbacks.YES)
async def broadcast_confirm(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    if not await _ensure_admin(call, session, "admin_broadcast.confirm"):
        return

    data = await state.get_data()
    payload = data.get("payload")
    if not isinstance(payload, dict):
        await state.clear()
        await edit_text_safe(call, "Нет данных рассылки 😕", reply_markup=admin_menu_kb())
        await call.answer()
        return

    await edit_text_safe(call, "⏳ Начинаю рассылку…", reply_markup=None)

    users = await get_all_user_tg_ids(session)
    sent = 0
    failed = 0

    for tg_id in users:
        try:
            await _send_payload(call.bot, tg_id, payload)
            sent += 1
        except Exception as e:
            failed += 1
            logger.warning("BROADCAST_FAIL tg_id=%s err=%s", tg_id, e)
        await asyncio.sleep(0.03)

    await state.clear()
    await edit_text_safe(
        call,
        f"✅ Рассылка завершена.\n\n"
        f"Отправлено: {sent}\n"
        f"Ошибок: {failed}",
        reply_markup=admin_menu_kb(),
    )
    await call.answer()
