from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.promo_code import PromoCode
from app.models.promo_redemption import PromoRedemption
from app.models.user import User
from app.repository.generations import (
    ensure_default_subscription,
    grant_photo_generation,
    grant_video_generation,
)


class PromoError(RuntimeError):
    pass


async def create_promo_code(
    session: AsyncSession,
    *,
    code: str,
    bonus_photo: int,
    bonus_video: int,
    max_uses: int,
) -> PromoCode:
    code = (code or "").strip()
    if not code:
        raise PromoError("Промокод пустой")
    if max_uses <= 0:
        raise PromoError("Количество активаций должно быть > 0")

    existing = await session.scalar(select(PromoCode).where(PromoCode.code == code))
    if existing:
        raise PromoError("Промокод уже существует")

    promo = PromoCode(
        code=code,
        bonus_photo=max(0, int(bonus_photo)),
        bonus_video=max(0, int(bonus_video)),
        max_uses=int(max_uses),
        used_count=0,
    )
    session.add(promo)
    await session.commit()
    await session.refresh(promo)
    return promo


async def redeem_promo_code(
    session: AsyncSession, *, tg_id: int, code: str
) -> PromoCode:
    code = (code or "").strip()
    if not code:
        raise PromoError("Промокод пустой")

    promo = await session.scalar(select(PromoCode).where(PromoCode.code == code))
    if not promo:
        raise PromoError("Промокод не найден")

    user = await session.scalar(select(User).where(User.tg_id == tg_id))
    if not user:
        raise PromoError("Пользователь не найден")

    already = await session.scalar(
        select(PromoRedemption.id).where(
            PromoRedemption.promo_id == promo.id,
            PromoRedemption.user_id == user.id,
        )
    )
    if already:
        raise PromoError("Этот промокод уже активирован вами")

    if int(promo.used_count) >= int(promo.max_uses):
        raise PromoError("Лимит активаций по промокоду исчерпан")

    await ensure_default_subscription(session, tg_id)

    result = await session.execute(
        update(PromoCode)
        .where(PromoCode.id == promo.id, PromoCode.used_count < PromoCode.max_uses)
        .values(used_count=PromoCode.used_count + 1)
    )
    if result.rowcount != 1:
        raise PromoError("Лимит активаций по промокоду исчерпан")
    session.add(
        PromoRedemption(promo_id=promo.id, user_id=user.id)
    )
    await session.commit()

    if promo.bonus_photo > 0:
        await grant_photo_generation(session, tg_id, delta=int(promo.bonus_photo))
    if promo.bonus_video > 0:
        await grant_video_generation(session, tg_id, delta=int(promo.bonus_video))

    return promo


async def get_last_promo_codes(
    session: AsyncSession, limit: int = 10
) -> list[PromoCode]:
    result = await session.execute(
        select(PromoCode).order_by(PromoCode.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())
