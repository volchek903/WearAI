from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy import update, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session_factory
from app.models.user import User
from app.repository.generations import ensure_default_subscription, grant_photo_generation

logger = logging.getLogger(__name__)

CHANNEL_ID = -1003494890507
CHANNEL_URL = "https://t.me/WearAIOfficial"


async def is_user_in_channel(bot: Bot, tg_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=tg_id)
    except TelegramBadRequest as e:
        logger.warning("channel check failed tg_id=%s err=%s", tg_id, e)
        return False
    status = getattr(member, "status", "") or ""
    return status in {"member", "administrator", "creator"}


async def mark_reminder_sent(session: AsyncSession, tg_id: int) -> None:
    await session.execute(
        update(User)
        .where(User.tg_id == tg_id)
        .values(free_channel_reminder_sent=True)
    )
    await session.commit()


async def start_bonus_pending(session: AsyncSession, tg_id: int) -> bool:
    result = await session.execute(
        update(User)
        .where(
            User.tg_id == tg_id,
            User.free_channel_bonus_used.is_(False),
            User.free_channel_bonus_pending.is_(False),
        )
        .values(free_channel_bonus_pending=True)
    )
    await session.commit()
    return result.rowcount == 1


async def finish_bonus(session: AsyncSession, tg_id: int) -> None:
    await session.execute(
        update(User)
        .where(User.tg_id == tg_id)
        .values(free_channel_bonus_used=True, free_channel_bonus_pending=False)
    )
    await session.commit()


async def bonus_already_used(session: AsyncSession, tg_id: int) -> bool:
    used = await session.scalar(
        select(User.free_channel_bonus_used).where(User.tg_id == tg_id)
    )
    return bool(used)


async def _send_message_safe(
    bot: Bot,
    tg_id: int,
    text: str,
    *,
    log_context: str,
    **kwargs,
) -> None:
    try:
        await bot.send_message(tg_id, text, **kwargs)
    except TelegramForbiddenError:
        logger.info("%s skipped tg_id=%s reason=bot_blocked", log_context, tg_id)
    except Exception:
        logger.exception("%s failed tg_id=%s", log_context, tg_id)


async def schedule_bonus_grant(bot: Bot, tg_id: int, delay_s: int = 60) -> None:
    async def _job() -> None:
        await asyncio.sleep(delay_s)
        async with session_factory() as session:
            await ensure_default_subscription(session, tg_id)
            await grant_photo_generation(session, tg_id, delta=1)
            await finish_bonus(session, tg_id)
        await _send_message_safe(
            bot,
            tg_id,
            "🎁 Начислены кредиты на 1 бесплатную фото-генерацию!",
            log_context="bonus message",
        )

    asyncio.create_task(_job())


async def schedule_free_bonus_reminder(bot: Bot, tg_id: int, delay_s: int = 600) -> None:
    async def _job() -> None:
        await asyncio.sleep(delay_s)
        async with session_factory() as session:
            used = await session.scalar(
                select(User.free_channel_bonus_used).where(User.tg_id == tg_id)
            )
            sent = await session.scalar(
                select(User.free_channel_reminder_sent).where(User.tg_id == tg_id)
            )
            if used or sent:
                return
            await mark_reminder_sent(session, tg_id)

        await _send_message_safe(
            bot,
            tg_id,
            "Хочешь получить ещё одну бесплатную фото-генерацию?\n"
            "Подпишись на канал и нажми кнопку ниже 👇",
            log_context="reminder",
            reply_markup=free_channel_kb(),
        )

    asyncio.create_task(_job())


def free_channel_kb():
    from aiogram.types import InlineKeyboardMarkup
    from app.keyboards.utils import make_button

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_button(text="Перейти в канал", url=CHANNEL_URL)],
            [make_button(text="✅ Я подписался", callback_data="extra:free:check")],
        ]
    )
