from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.photo_defaults import (
    ASPECT_RATIOS,
    RESOLUTIONS,
    OUTPUT_FORMATS,
    next_in_cycle,
)
from app.keyboards.menu import (
    MenuCallbacks,
    SettingsCallbacks,
    main_menu_kb,
    photo_settings_kb,
)
from app.repository.photo_settings import (
    ensure_photo_settings,
    update_photo_settings,
    reset_photo_settings,
)
from app.repository.users import get_user_by_tg_id
from app.utils.tg_edit import edit_text_safe

router = Router()


def render_settings_text(aspect_ratio: str, resolution: str, output_format: str) -> str:
    return (
        "⚙️ Настройки генерации фото\n\n"
        f"• input.aspect_ratio: <b>{aspect_ratio}</b>\n"
        f"• resolution: <b>{resolution}</b>\n"
        f"• output_format: <b>{output_format}</b>\n\n"
        "Нажимай на параметр, чтобы изменить ✨"
    )


async def _get_user_db_id(session: AsyncSession, tg_id: int) -> int:
    user = await get_user_by_tg_id(session, tg_id)
    if user is None:
        raise RuntimeError("User not found in DB. Use /start first.")
    return user.id


@router.callback_query(F.data == MenuCallbacks.SETTINGS)
async def open_settings(call: CallbackQuery, session: AsyncSession) -> None:
    user_id = await _get_user_db_id(session, call.from_user.id)
    s = await ensure_photo_settings(session, user_id)

    await edit_text_safe(
        call,
        render_settings_text(s.aspect_ratio, s.resolution, s.output_format),
        reply_markup=photo_settings_kb(s),
    )
    await call.answer()


@router.callback_query(F.data == SettingsCallbacks.ASPECT)
async def change_aspect(call: CallbackQuery, session: AsyncSession) -> None:
    user_id = await _get_user_db_id(session, call.from_user.id)
    s = await ensure_photo_settings(session, user_id)

    new_value = next_in_cycle(s.aspect_ratio, ASPECT_RATIOS)
    s = await update_photo_settings(session, user_id, aspect_ratio=new_value)

    await edit_text_safe(
        call,
        render_settings_text(s.aspect_ratio, s.resolution, s.output_format),
        reply_markup=photo_settings_kb(s),
    )
    await call.answer("✅ Соотношение изменено")


@router.callback_query(F.data == SettingsCallbacks.RESOLUTION)
async def change_resolution(call: CallbackQuery, session: AsyncSession) -> None:
    user_id = await _get_user_db_id(session, call.from_user.id)
    s = await ensure_photo_settings(session, user_id)

    new_value = next_in_cycle(s.resolution, RESOLUTIONS)
    s = await update_photo_settings(session, user_id, resolution=new_value)

    await edit_text_safe(
        call,
        render_settings_text(s.aspect_ratio, s.resolution, s.output_format),
        reply_markup=photo_settings_kb(s),
    )
    await call.answer("✅ Разрешение изменено")


@router.callback_query(F.data == SettingsCallbacks.FORMAT)
async def change_format(call: CallbackQuery, session: AsyncSession) -> None:
    user_id = await _get_user_db_id(session, call.from_user.id)
    s = await ensure_photo_settings(session, user_id)

    new_value = next_in_cycle(s.output_format, OUTPUT_FORMATS)
    s = await update_photo_settings(session, user_id, output_format=new_value)

    await edit_text_safe(
        call,
        render_settings_text(s.aspect_ratio, s.resolution, s.output_format),
        reply_markup=photo_settings_kb(s),
    )
    await call.answer("✅ Формат изменён")


@router.callback_query(F.data == SettingsCallbacks.RESET)
async def reset(call: CallbackQuery, session: AsyncSession) -> None:
    user_id = await _get_user_db_id(session, call.from_user.id)
    s = await reset_photo_settings(session, user_id)

    await edit_text_safe(
        call,
        render_settings_text(s.aspect_ratio, s.resolution, s.output_format),
        reply_markup=photo_settings_kb(s),
    )
    await call.answer("🔄 Сброшено")


@router.callback_query(F.data == SettingsCallbacks.BACK)
async def back(call: CallbackQuery) -> None:
    await edit_text_safe(call, "Выбери режим ниже 👇✨", reply_markup=main_menu_kb())
    await call.answer()
