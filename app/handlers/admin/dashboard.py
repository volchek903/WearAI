from __future__ import annotations

from aiogram import F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.admin import AdminCallbacks, admin_menu_kb
from app.repository.analytics import (
    get_model_breakdown,
    get_revenue_stats,
    get_section_breakdown,
    get_top_sections,
    get_user_entry_stats,
)
from app.repository.admin import get_users_stats
from app.repository.referrals import get_top_referrers_last_week
from app.utils.tg_edit import edit_text_safe

from .common import ensure_admin, router


@router.callback_query(F.data == AdminCallbacks.STATS)
async def admin_stats(call: CallbackQuery, session: AsyncSession) -> None:
    if not await ensure_admin(call, session, "admin_panel.stats"):
        return
    total_users, active_subs, total_photos, total_videos, total_music = (
        await get_users_stats(session)
    )
    payments_count, revenue_rub = await get_revenue_stats(session)
    entries = await get_user_entry_stats(session)

    text = (
        "📊 <b>Статистика</b>\n\n"
        f"💰 Заработано: <code>{revenue_rub} ₽</code>\n"
        f"🧾 Оплат подтверждено: <code>{payments_count}</code>\n\n"
        f"👥 Пользователей за всё время: <code>{entries['all_time']}</code>\n"
        f"🗓 За 30 дней: <code>{entries['month']}</code>\n"
        f"📅 За 7 дней: <code>{entries['week']}</code>\n"
        f"⏱ За 24 часа: <code>{entries['day']}</code>\n\n"
        f"👥 Всего пользователей в БД: <code>{total_users}</code>\n"
        f"✅ Активных подписок: <code>{active_subs}</code>\n"
        f"🖼️ Сгенерировано фото: <code>{total_photos}</code>\n"
        f"🎬 Сгенерировано видео: <code>{total_videos}</code>\n"
        f"🎵 Сгенерировано музыки: <code>{total_music}</code>"
    )

    await edit_text_safe(call, text, reply_markup=admin_menu_kb())
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.ANALYTICS)
async def admin_analytics(call: CallbackQuery, session: AsyncSession) -> None:
    if not await ensure_admin(call, session, "admin_panel.analytics"):
        return

    top_sections = await get_top_sections(session, limit=5)
    breakdown = await get_section_breakdown(session)
    model_breakdown = await get_model_breakdown(session)

    lines = ["📈 <b>Аналитика шаблонов и моделей</b>", ""]
    lines.append("🏆 Топ 5 шаблонов / разделов:")
    if not top_sections:
        lines.append("Пока нет данных.")
    else:
        for idx, (section, cnt) in enumerate(top_sections, start=1):
            lines.append(f"{idx}. <b>{section}</b> — {cnt}")

    lines.append("")
    lines.append("🧩 По разделам:")
    if not breakdown:
        lines.append("Пока нет данных.")
    else:
        for section, photo_cnt, video_cnt, total_cnt in breakdown:
            lines.append(
                f"• <b>{section}</b> — всего {total_cnt}, фото {photo_cnt}, видео {video_cnt}"
            )

    lines.append("")
    lines.append("🤖 По моделям:")
    for model_title, total_cnt in model_breakdown:
        lines.append(f"• <b>{model_title}</b> — {total_cnt}")

    await edit_text_safe(call, "\n".join(lines), reply_markup=admin_menu_kb())
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.TOP_REFERRALS)
async def admin_top_referrals(call: CallbackQuery, session: AsyncSession) -> None:
    if not await ensure_admin(call, session, "admin_panel.top_referrals"):
        return

    rows = await get_top_referrers_last_week(session, limit=10)
    if not rows:
        text = "🏆 <b>Топ рефералов</b>\n\nЗа последние 7 дней нет рефералов."
        await edit_text_safe(call, text, reply_markup=admin_menu_kb())
        await call.answer()
        return

    lines = []
    for i, row in enumerate(rows, start=1):
        username = row.get("username")
        tg_id = row.get("tg_id")
        count = row.get("count", 0)
        who = f"@{username}" if username else f"tg_id {tg_id}"
        lines.append(f"{i}. {who} — {count}")

    text = "🏆 <b>Топ рефералов за 7 дней</b>\n\n" + "\n".join(lines)
    await edit_text_safe(call, text, reply_markup=admin_menu_kb())
    await call.answer()
