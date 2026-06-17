from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.repository.app_settings import (
    MODEL_PRICE_NANO_BANANA_KEY,
    get_model_price_credits,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
else:
    AsyncSession = Any


def format_credits(credits: int) -> str:
    value = int(credits)
    abs_value = abs(value)
    mod100 = abs_value % 100
    mod10 = abs_value % 10
    if 11 <= mod100 <= 14:
        suffix = "кредитов"
    elif mod10 == 1:
        suffix = "кредит"
    elif 2 <= mod10 <= 4:
        suffix = "кредита"
    else:
        suffix = "кредитов"
    return f"{value} {suffix}"


def single_generation_price_line(credits: int) -> str:
    return f"💳 Цена за 1 генерацию: <b>{format_credits(credits)}</b>."


async def build_single_generation_price_line(
    session: AsyncSession,
    model_key: str = MODEL_PRICE_NANO_BANANA_KEY,
) -> str:
    credits = await get_model_price_credits(session, model_key)
    return single_generation_price_line(credits)
