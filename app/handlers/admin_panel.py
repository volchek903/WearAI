from __future__ import annotations

import asyncio
import logging
import os
import sys

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.admin import (
    AdminCallbacks,
    admin_menu_kb,
    admin_users_nav_kb,
    admin_promo_kb,
)
from app.keyboards.confirm import yes_no_kb, ConfirmCallbacks
from app.repository.admin import is_admin, get_users_page, get_users_stats
from app.repository.admin_actions import log_admin_action
from app.repository.promo import create_promo_code, get_last_promo_codes, PromoError
from app.states.admin import AdminPromoFSM
from app.utils.tg_edit import edit_text_safe

router = Router()
logger = logging.getLogger(__name__)


async def _ensure_admin(call: CallbackQuery, session: AsyncSession, action: str) -> bool:
    tg_id = call.from_user.id
    if await is_admin(session, tg_id):
        await log_admin_action(
            session, tg_id=tg_id, action=action, data=str(call.data or "")
        )
        return True
    logger.warning("ADMIN_DENY action=%s tg_id=%s data=%s", action, tg_id, call.data)
    await call.answer("Недостаточно прав", show_alert=True)
    return False


async def _restart_process(message: Message) -> None:
    # Give the bot time to send the confirmation message before restarting.
    await message.answer("🔄 Перезапускаю бота…")
    await asyncio.sleep(1)
    os.execv(sys.executable, [sys.executable] + sys.argv)


@router.message(Command("admin"))
async def admin_entry(message: Message, session: AsyncSession) -> None:
    if not await is_admin(session, message.from_user.id):
        return
    await message.answer("⚙️ Админка", reply_markup=admin_menu_kb())


@router.message(Command("restart"))
async def admin_restart(message: Message, session: AsyncSession) -> None:
    if message.from_user.id != 830091750:
        return
    await _restart_process(message)


@router.callback_query(F.data == AdminCallbacks.STATS)
async def admin_stats(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _ensure_admin(call, session, "admin_panel.stats"):
        return
    total_users, active_subs, total_photos, total_videos = await get_users_stats(
        session
    )

    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Всего пользователей: <code>{total_users}</code>\n"
        f"✅ Активных подписок: <code>{active_subs}</code>\n"
        f"🖼️ Сгенерировано фото: <code>{total_photos}</code>\n"
        f"🎬 Сгенерировано видео: <code>{total_videos}</code>"
    )

    await edit_text_safe(call, text, reply_markup=admin_menu_kb())
    await call.answer()


def _parse_users_page(data: str) -> int:
    try:
        _, page = data.rsplit(":", 1)
        return max(1, int(page))
    except Exception:
        return 1


async def _render_users_page(
    call: CallbackQuery, session: AsyncSession, page: int
) -> None:
    limit = 10
    offset = (page - 1) * limit
    rows, total_users = await get_users_page(session, limit=limit, offset=offset)

    if not rows:
        text = "👥 <b>Пользователи</b>\n\nПока пусто 💤"
        reply_markup = admin_menu_kb()
    else:
        lines: list[str] = []
        for uid, tg_id, username, created_at, photos, videos in rows:
            uname = username or "-"
            lines.append(
                f"• id={uid} tg={tg_id} @{uname} ({created_at:%Y-%m-%d}) "
                f"фото={int(photos or 0)} видео={int(videos or 0)}"
            )
        total_pages = max(1, (total_users + limit - 1) // limit)
        text = (
            f"👥 <b>Пользователи</b> (стр. {page}/{total_pages})\n\n"
            + "\n".join(lines)
        )
        reply_markup = admin_users_nav_kb(
            page=page,
            has_prev=page > 1,
            has_next=offset + limit < total_users,
        )

    await edit_text_safe(call, text, reply_markup=reply_markup)
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.USERS)
async def admin_users(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _ensure_admin(call, session, "admin_panel.users"):
        return
    await _render_users_page(call, session, page=1)


@router.callback_query(F.data.startswith(f"{AdminCallbacks.USERS_PAGE}:"))
async def admin_users_page(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _ensure_admin(call, session, "admin_panel.users_page"):
        return
    page = _parse_users_page(call.data or "")
    await _render_users_page(call, session, page=page)


@router.callback_query(F.data == AdminCallbacks.BACK)
async def admin_back(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _ensure_admin(call, session, "admin_panel.back"):
        return
    await edit_text_safe(call, "⚙️ Админка", reply_markup=admin_menu_kb())
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.PROMO)
async def admin_promo_menu(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _ensure_admin(call, session, "admin_panel.promo_menu"):
        return
    await edit_text_safe(call, "🎟 Промокоды", reply_markup=admin_promo_kb())
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.CREATE_PROMO)
async def admin_promo_start(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    if not await _ensure_admin(call, session, "admin_panel.create_promo"):
        return
    await state.clear()
    await state.set_state(AdminPromoFSM.code)
    await edit_text_safe(call, "Введи промокод ✍️")
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.LIST_PROMO)
async def admin_promo_list(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _ensure_admin(call, session, "admin_panel.promo_list"):
        return
    promos = await get_last_promo_codes(session, limit=10)
    if not promos:
        text = "🎟 <b>Промокоды</b>\n\nПока пусто 💤"
    else:
        lines: list[str] = []
        for p in promos:
            lines.append(
                f"• <code>{p.code}</code> "
                f"фото={p.bonus_photo} видео={p.bonus_video} "
                f"использовано {p.used_count}/{p.max_uses}"
            )
        text = "🎟 <b>Последние 10 промокодов</b>\n\n" + "\n".join(lines)
    await edit_text_safe(call, text, reply_markup=admin_promo_kb())
    await call.answer()


@router.message(AdminPromoFSM.code)
async def admin_promo_code_in(message: Message, state: FSMContext) -> None:
    code = (message.text or "").strip()
    if not code:
        await message.answer("Промокод пустой. Введи ещё раз ✍️")
        return
    await state.update_data(code=code)
    await state.set_state(AdminPromoFSM.kind)

    kb = InlineKeyboardBuilder()
    kb.button(text="🖼 Только фото", callback_data=AdminCallbacks.promo_type("photo"))
    kb.button(text="🎬 Только видео", callback_data=AdminCallbacks.promo_type("video"))
    kb.button(text="🖼+🎬 Фото и видео", callback_data=AdminCallbacks.promo_type("both"))
    kb.adjust(1)
    await message.answer("Что выдаёт промокод?", reply_markup=kb.as_markup())


@router.callback_query(
    AdminPromoFSM.kind, F.data.startswith(f"{AdminCallbacks.PROMO_TYPE}:")
)
async def admin_promo_type(call: CallbackQuery, state: FSMContext) -> None:
    kind = (call.data or "").rsplit(":", 1)[-1].strip()
    if kind not in {"photo", "video", "both"}:
        await call.answer("Неверный тип", show_alert=True)
        return
    await state.update_data(kind=kind)
    if kind == "photo":
        await state.set_state(AdminPromoFSM.photo_count)
        await edit_text_safe(call, "Сколько фото-генераций выдаёт промокод?")
    elif kind == "video":
        await state.set_state(AdminPromoFSM.video_count)
        await edit_text_safe(call, "Сколько видео-генераций выдаёт промокод?")
    else:
        await state.set_state(AdminPromoFSM.photo_count)
        await edit_text_safe(call, "Сколько фото-генераций выдаёт промокод?")
    await call.answer()


@router.message(AdminPromoFSM.photo_count)
async def admin_promo_photo_count(message: Message, state: FSMContext) -> None:
    try:
        count = int((message.text or "").strip())
    except Exception:
        await message.answer("Нужно число. Введи ещё раз ✍️")
        return
    if count < 0:
        await message.answer("Число должно быть >= 0")
        return
    await state.update_data(photo_count=count)
    data = await state.get_data()
    kind = data.get("kind")
    if kind == "photo":
        await state.update_data(video_count=0)
        await state.set_state(AdminPromoFSM.max_uses)
        await message.answer("Сколько пользователей может активировать промокод?")
    else:
        await state.set_state(AdminPromoFSM.video_count)
        await message.answer("Сколько видео-генераций выдаёт промокод?")


@router.message(AdminPromoFSM.video_count)
async def admin_promo_video_count(message: Message, state: FSMContext) -> None:
    try:
        count = int((message.text or "").strip())
    except Exception:
        await message.answer("Нужно число. Введи ещё раз ✍️")
        return
    if count < 0:
        await message.answer("Число должно быть >= 0")
        return
    await state.update_data(video_count=count)
    data = await state.get_data()
    kind = data.get("kind")
    if kind == "video":
        await state.update_data(photo_count=0)
    await state.set_state(AdminPromoFSM.max_uses)
    await message.answer("Сколько пользователей может активировать промокод?")


@router.message(AdminPromoFSM.max_uses)
async def admin_promo_max_uses(message: Message, state: FSMContext) -> None:
    try:
        count = int((message.text or "").strip())
    except Exception:
        await message.answer("Нужно число. Введи ещё раз ✍️")
        return
    if count <= 0:
        await message.answer("Число должно быть > 0")
        return

    data = await state.get_data()
    code = data.get("code")
    photo_count = int(data.get("photo_count") or 0)
    video_count = int(data.get("video_count") or 0)

    await state.update_data(max_uses=count)
    await state.set_state(AdminPromoFSM.confirm)

    await message.answer(
        "Проверь данные промокода:\n\n"
        f"Код: <b>{code}</b>\n"
        f"Фото-генераций: <b>{photo_count}</b>\n"
        f"Видео-генераций: <b>{video_count}</b>\n"
        f"Лимит активаций: <b>{count}</b>\n\n"
        "Всё верно?",
        reply_markup=yes_no_kb(yes_text="✅ Создать", no_text="❌ Отменить"),
    )


@router.callback_query(AdminPromoFSM.confirm, F.data == ConfirmCallbacks.NO)
async def admin_promo_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit_text_safe(call, "Создание промокода отменено.", reply_markup=admin_menu_kb())
    await call.answer()


@router.callback_query(AdminPromoFSM.confirm, F.data == ConfirmCallbacks.YES)
async def admin_promo_confirm(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    code = data.get("code") or ""
    photo_count = int(data.get("photo_count") or 0)
    video_count = int(data.get("video_count") or 0)
    max_uses = int(data.get("max_uses") or 0)

    try:
        await create_promo_code(
            session,
            code=code,
            bonus_photo=photo_count,
            bonus_video=video_count,
            max_uses=max_uses,
        )
    except PromoError as e:
        await edit_text_safe(call, f"Ошибка: {e}", reply_markup=admin_menu_kb())
        await state.clear()
        await call.answer()
        return

    await state.clear()
    await edit_text_safe(call, "✅ Промокод создан.", reply_markup=admin_menu_kb())
    await call.answer()
