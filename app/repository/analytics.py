from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generation_analytics import GenerationAnalytics
from app.models.payment import Payment, PaymentStatus
from app.models.user import User

MODEL_SECTION_TITLES = {
    "nano_banana": "Nano Banana 2",
    "nano_banana_pro": "Nano Banana Pro",
    "seedream_v5_lite": "Seedream 5 Lite",
    "seedream_v45": "Seedream 4.5",
    "wan_27": "Wan 2.7",
    "gpt_image_2_edit": "GPT Image 2 Edit",
    "gpt_image_2_text_to_image": "GPT Image 2 Text-to-Image",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def log_generation_event(
    session: AsyncSession,
    *,
    tg_id: int,
    section: str,
    kind: str,
) -> None:
    session.add(
        GenerationAnalytics(
            tg_id=int(tg_id),
            section=(section or "unknown")[:64],
            kind=(kind or "unknown")[:16],
        )
    )
    await session.commit()


async def get_revenue_stats(session: AsyncSession) -> tuple[int, int]:
    row = (
        await session.execute(
            select(
                func.count(Payment.id),
                func.sum(Payment.amount),
            ).where(Payment.status == PaymentStatus.CONFIRMED)
        )
    ).first()
    if not row:
        return 0, 0
    return int(row[0] or 0), int(row[1] or 0)


async def get_user_entry_stats(session: AsyncSession) -> dict[str, int]:
    now = _utcnow()
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)
    day_ago = now - timedelta(hours=24)

    row = (
        await session.execute(
            select(
                func.count(User.id),
                func.sum(case((User.created_at >= month_ago, 1), else_=0)),
                func.sum(case((User.created_at >= week_ago, 1), else_=0)),
                func.sum(case((User.created_at >= day_ago, 1), else_=0)),
            )
        )
    ).first()
    return {
        "all_time": int((row[0] if row else 0) or 0),
        "month": int((row[1] if row else 0) or 0),
        "week": int((row[2] if row else 0) or 0),
        "day": int((row[3] if row else 0) or 0),
    }


async def get_top_sections(session: AsyncSession, *, limit: int = 5) -> list[tuple[str, int]]:
    rows = await session.execute(
        select(
            GenerationAnalytics.section,
            func.count(GenerationAnalytics.id).label("cnt"),
        )
        .group_by(GenerationAnalytics.section)
        .order_by(func.count(GenerationAnalytics.id).desc(), GenerationAnalytics.section.asc())
        .limit(limit)
    )
    return [(str(section), int(cnt or 0)) for section, cnt in rows.all()]


async def get_section_breakdown(
    session: AsyncSession,
) -> list[tuple[str, int, int, int]]:
    rows = await session.execute(
        select(
            GenerationAnalytics.section,
            func.sum(case((GenerationAnalytics.kind == "photo", 1), else_=0)).label("photo_cnt"),
            func.sum(case((GenerationAnalytics.kind == "video", 1), else_=0)).label("video_cnt"),
            func.count(GenerationAnalytics.id).label("total_cnt"),
        )
        .group_by(GenerationAnalytics.section)
        .order_by(func.count(GenerationAnalytics.id).desc(), GenerationAnalytics.section.asc())
    )
    return [
        (str(section), int(photo_cnt or 0), int(video_cnt or 0), int(total_cnt or 0))
        for section, photo_cnt, video_cnt, total_cnt in rows.all()
    ]


async def get_model_breakdown(session: AsyncSession) -> list[tuple[str, int]]:
    rows = await session.execute(
        select(
            GenerationAnalytics.section,
            func.count(GenerationAnalytics.id).label("cnt"),
        )
        .where(GenerationAnalytics.section.in_(tuple(MODEL_SECTION_TITLES)))
        .group_by(GenerationAnalytics.section)
    )
    counts = {str(section): int(cnt or 0) for section, cnt in rows.all()}
    return [
        (title, counts.get(section, 0))
        for section, title in MODEL_SECTION_TITLES.items()
    ]
