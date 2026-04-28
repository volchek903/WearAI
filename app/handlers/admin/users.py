from __future__ import annotations

from aiogram import F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.admin import AdminCallbacks, admin_menu_kb, admin_users_nav_kb
from app.repository.admin import get_users_page
from app.utils.tg_edit import edit_text_safe

from .common import ensure_admin, parse_users_page, router


async def render_users_page(
    call: CallbackQuery,
    session: AsyncSession,
    page: int,
) -> None:
    limit = 10
    offset = (page - 1) * limit
    rows, total_users = await get_users_page(session, limit=limit, offset=offset)

    if not rows:
        text = "👥 <b>Пользователи</b>\n\nПока пусто 💤"
        reply_markup = admin_menu_kb()
    else:
        lines: list[str] = []
        for uid, tg_id, username, created_at, credits, free_credits, photos, videos in rows:
            uname = username or "-"
            lines.append(
                f"• id={uid} tg={tg_id} @{uname} ({created_at:%Y-%m-%d}) "
                f"осн={int(credits or 0)} free={int(free_credits or 0)} "
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
    if not await ensure_admin(call, session, "admin_panel.users"):
        return
    await render_users_page(call, session, page=1)


@router.callback_query(F.data.startswith(f"{AdminCallbacks.USERS_PAGE}:"))
async def admin_users_page(call: CallbackQuery, session: AsyncSession) -> None:
    if not await ensure_admin(call, session, "admin_panel.users_page"):
        return
    page = parse_users_page(call.data or "")
    await render_users_page(call, session, page=page)
