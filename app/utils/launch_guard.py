from __future__ import annotations

from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.repository.generations import is_launch_subscription
from app.utils.support_text import launch_limits_message
from app.utils.tg_edit import edit_text_safe
from app.utils.tg_callback import safe_answer


async def block_launch_for_call(
    call: CallbackQuery,
    session: AsyncSession,
    *,
    reply_markup=None,
) -> bool:
    if await is_launch_subscription(session, call.from_user.id):
        await edit_text_safe(
            call,
            launch_limits_message(),
            reply_markup=reply_markup,
        )
        await safe_answer(call)
        return True
    return False
