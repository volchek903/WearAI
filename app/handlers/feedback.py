from __future__ import annotations

import logging
from typing import Any

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.keyboards.feedback import back_to_menu_kb, FeedbackCallbacks
from app.keyboards.menu import main_menu_kb
from app.states.feedback_flow import FeedbackFlow

router = Router()
logger = logging.getLogger(__name__)

ADMIN_TG_ID = 830091750

TG_TEXT_LIMIT = 3800
TG_CAPTION_LIMIT = 900


def _chunk_text(text: str, limit: int = TG_TEXT_LIMIT) -> list[str]:
    text = text or ""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    buf: list[str] = []
    size = 0

    for line in text.splitlines(True):
        if size + len(line) > limit and buf:
            chunks.append("".join(buf))
            buf = []
            size = 0
        buf.append(line)
        size += len(line)

    if buf:
        chunks.append("".join(buf))

    return chunks


async def _send_admin_long_text(bot: Bot, text: str) -> None:
    for part in _chunk_text(text):
        await bot.send_message(ADMIN_TG_ID, part)


def _cap_caption(caption: str) -> str:
    caption = caption or ""
    return (
        caption
        if len(caption) <= TG_CAPTION_LIMIT
        else (caption[: TG_CAPTION_LIMIT - 3] + "...")
    )


async def _send_file_id_to_admin(
    bot: Bot,
    *,
    kind: str,  # "photo" | "document"
    file_id: str,
    caption: str,
) -> None:
    if not file_id:
        return

    caption = _cap_caption(caption)

    try:
        if kind == "document":
            await bot.send_document(ADMIN_TG_ID, document=file_id, caption=caption)
        else:
            await bot.send_photo(ADMIN_TG_ID, photo=file_id, caption=caption)
    except Exception as e:
        logger.warning("Failed to send file_id to admin. kind=%s err=%s", kind, e)


def _format_report(payload: dict[str, Any], user_text: str) -> str:
    scenario = payload.get("scenario") or "unknown"
    user_tg_id = payload.get("user_tg_id")
    username = payload.get("username") or ""

    lines = [
        "WearAI — сообщение об ошибке",
        f"Сценарий: {scenario}",
        (
            f"От: @{username} (tg_id={user_tg_id})"
            if username
            else f"От: tg_id={user_tg_id}"
        ),
        "",
        "Сообщение пользователя:",
        user_text.strip() if user_text else "(пусто)",
        "",
        "KIE prompt:",
        (payload.get("kie_prompt") or "").strip(),
        "",
    ]

    if scenario == "model":
        lines += [
            "model_desc:",
            (payload.get("model_desc") or "").strip(),
            "",
            "presentation_desc:",
            (payload.get("presentation_desc") or "").strip(),
            "",
        ]

    if scenario == "tryon":
        lines += [
            "tryon_desc:",
            (payload.get("tryon_desc") or "").strip(),
            "",
        ]

    lines += [
        "IN file_id(s):",
        str(payload.get("input_photos") or ""),
        "",
        "OUT file_id(s):",
        str(payload.get("output_files") or ""),
    ]

    return "\n".join(lines).strip()


@router.callback_query(FeedbackFlow.text, F.data == FeedbackCallbacks.MENU)
async def feedback_back_to_menu(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None:
        await call.answer()
        return

    await state.clear()
    await call.message.answer("Ок. Возвращаю в меню.", reply_markup=main_menu_kb())
    await call.answer()


@router.callback_query(FeedbackFlow.choice, F.data == FeedbackCallbacks.BUG)
async def feedback_bug(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None:
        await call.answer()
        return

    await state.set_state(FeedbackFlow.text)
    await call.message.answer(
        "Опиши, пожалуйста, что именно не так (1–3 предложения).\n"
        "Например: «не тот товар», «исказился цвет», «лицо поменялось», «плохие руки» и т.д.",
        reply_markup=back_to_menu_kb(),
    )
    await call.answer()


@router.message(FeedbackFlow.text, F.text)
async def feedback_text_in(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    payload = data.get("feedback_payload")
    if not isinstance(payload, dict):
        payload = {}

    payload.setdefault("user_tg_id", message.from_user.id)
    payload.setdefault("username", message.from_user.username or "")

    user_text = (message.text or "").strip()

    report_text = _format_report(payload, user_text)
    await _send_admin_long_text(message.bot, report_text)

    scenario = payload.get("scenario", "unknown")

    input_photos = payload.get("input_photos")

    if isinstance(input_photos, dict):
        for k, fid in input_photos.items():
            if isinstance(fid, str) and fid:
                await _send_file_id_to_admin(
                    message.bot,
                    kind="photo",
                    file_id=fid,
                    caption=f"IN ({scenario}): {k}",
                )

    elif isinstance(input_photos, list):
        for i, fid in enumerate(input_photos, start=1):
            if isinstance(fid, str) and fid:
                await _send_file_id_to_admin(
                    message.bot,
                    kind="photo",
                    file_id=fid,
                    caption=f"IN ({scenario}): product_photo_{i}",
                )

    output_files = payload.get("output_files") or []
    if isinstance(output_files, list):
        for i, item in enumerate(output_files, start=1):
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "photo").strip()
            fid = str(item.get("file_id") or "").strip()
            fname = str(item.get("filename") or f"result_{i}").strip()
            if fid:
                await _send_file_id_to_admin(
                    message.bot,
                    kind=kind,
                    file_id=fid,
                    caption=f"OUT ({scenario}): {fname}",
                )

    await message.answer(
        "Спасибо! Сообщение передано в поддержку.", reply_markup=main_menu_kb()
    )
    await state.clear()
