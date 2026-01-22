from __future__ import annotations

import html
import logging

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.validators import MAX_TEXT_LEN, is_text_too_long
from app.keyboards.help import HelpCallbacks, help_use_back_kb
from app.keyboards.confirm import yes_no_kb, review_edit_kb
from app.repository.users import upsert_user
from app.services.prompt_helper import generate_nano_banana_prompt_ru, PromptHelperError
from app.states.help_flow import HelpFlow
from app.states.model_flow import ModelFlow
from app.utils.tg_edit import edit_text_safe

router = Router()
logger = logging.getLogger(__name__)


def _tips_for_photo(kind: str) -> str:
    if kind == "product_photos":
        return (
            "Подсказка по фото товара 📸✨\n"
            "• Отправь 1–5 фото одним альбомом\n"
            "• Хороший свет, без сильных теней\n"
            "• Товар по центру, фон нейтральный\n"
            "• 1 общий кадр + 1–2 крупняка деталей\n\n"
            "Ок 😊 продолжай на этом шаге 👇"
        )
    if kind == "user_photo":
        return (
            "Подсказка по твоему фото 🤳✨\n"
            "• Ровный свет, без пересвета\n"
            "• Камера на уровне глаз\n"
            "• Однотонный фон — идеально\n\n"
            "Ок 😊 продолжай на этом шаге 👇"
        )
    if kind == "item_photo":
        return (
            "Подсказка по фото вещи 📦📸\n"
            "• Вещь целиком, спереди\n"
            "• Свет ровный, фон нейтральный\n"
            "• Без размытия и бликов\n\n"
            "Ок 😊 продолжай на этом шаге 👇"
        )
    return (
        "Подсказка ✨: отправь данные в хорошем качестве — так результат будет лучше."
    )


@router.callback_query(F.data.startswith(f"{HelpCallbacks.START}:"))
async def help_start(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await upsert_user(session, call.from_user.id, call.from_user.username)

    kind = call.data.split(":", 2)[2].strip()
    return_state = await state.get_state()
    await state.update_data(help_kind=kind, return_state=return_state)

    if kind in {"product_photos", "user_photo", "item_photo"}:
        await edit_text_safe(call, _tips_for_photo(kind))
        await call.answer()
        return

    await state.set_state(HelpFlow.input)

    if kind == "model_desc":
        text = (
            "Давай помогу с описанием модели 🛍✨\n\n"
            "Напиши коротко, что хочешь видеть:\n"
            "• пол/возраст\n"
            "• стиль (casual, street, business)\n"
            "• фон/свет\n"
            "• настроение/поза\n\n"
            "Сгенерирую промпт на русском для nano-banana-pro 😉"
        )
    elif kind == "presentation_desc":
        text = (
            "Давай помогу описать подачу товара ✨\n\n"
            "Напиши коротко:\n"
            "• что за товар\n"
            "• где он должен быть (на руке/ушах/ногтях и т.д.)\n"
            "• план (крупный/по пояс/портрет)\n"
            "• настроение/стиль\n\n"
            "Сгенерирую промпт на русском для nano-banana-pro 😉"
        )
    else:
        text = "Ок 🙂 Напиши детали, и я сделаю промпт на русском для nano-banana-pro."

    await edit_text_safe(call, text)
    await call.answer()


@router.message(HelpFlow.input)
async def help_input(message: Message, state: FSMContext) -> None:
    if not message.text or not message.text.strip():
        await message.answer("Напиши, пожалуйста, текстом 😊")
        return

    details = message.text.strip()

    if is_text_too_long(details):
        await message.answer(
            f"Ой 😅 Слишком длинно.\n"
            f"Максимум {MAX_TEXT_LEN} символов, а у тебя {len(details)}.\n"
            "Сократи, пожалуйста, и отправь ещё раз 🙌"
        )
        return

    data = await state.get_data()
    kind = (data.get("help_kind") or "").strip()

    try:
        generated = await generate_nano_banana_prompt_ru(
            section=kind, user_text=details
        )
    except PromptHelperError as e:
        logger.exception("Prompt helper failed: %s", e)
        await message.answer(
            "Не получилось сгенерировать промпт 😅\n"
            "Проверь, что в .env есть OPENROUTER_API_KEY, и попробуй ещё раз."
        )
        return
    except Exception as e:
        logger.exception("Unexpected error in prompt generation: %s", e)
        await message.answer(
            "Не получилось сгенерировать промпт 😅 Попробуй ещё раз чуть позже."
        )
        return

    await state.update_data(generated_text=generated)
    await state.set_state(HelpFlow.ready)

    safe = html.escape(generated)
    await message.answer(
        "Готово! ✨ Вот промпт на русском для <b>nano-banana-pro</b>:\n\n"
        f"<code>{safe}</code>\n\n"
        "Хочешь использовать его? 😉",
        reply_markup=help_use_back_kb(),
    )


@router.callback_query(HelpFlow.ready, F.data == HelpCallbacks.BACK)
async def help_back(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    return_state = data.get("return_state")

    if return_state:
        await state.set_state(return_state)
    else:
        await state.clear()

    await edit_text_safe(call, "Ок 😄 возвращаю к вводу. Продолжай 👇")
    await call.answer()


@router.callback_query(HelpFlow.ready, F.data == HelpCallbacks.USE)
async def help_use(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    kind = data.get("help_kind")
    return_state = data.get("return_state")
    generated = data.get("generated_text", "")

    if not return_state:
        await state.clear()
        await edit_text_safe(call, "Ок ✅")
        await call.answer()
        return

    if kind == "model_desc" and return_state == ModelFlow.model_desc.state:
        await state.set_state(ModelFlow.confirm_model_desc)
        await state.update_data(model_desc=generated)

        safe = html.escape(generated)
        await edit_text_safe(
            call,
            "Супер! 😊 Вот описание/промпт для модели:\n"
            f"<code>{safe}</code>\n\n"
            "Всё верно? ✅",
            reply_markup=yes_no_kb(yes_text="✅ Да", no_text="✏️ Изменить"),
        )
        await call.answer()
        return

    if (
        kind == "presentation_desc"
        and return_state == ModelFlow.presentation_desc.state
    ):
        await state.update_data(presentation_desc=generated)
        await state.set_state(ModelFlow.review)

        d = await state.get_data()
        desc = d.get("model_desc", "")
        photos = d.get("product_photos", []) or []

        safe_desc = html.escape(desc)
        safe_gen = html.escape(generated)

        await edit_text_safe(
            call,
            "Давай проверим ✅😊\n\n"
            f"1) Описание модели: <code>{safe_desc}</code>\n"
            f"2) Фото товара: {len(photos)} шт. 📸\n"
            f"3) Подача товара: <code>{safe_gen}</code>\n\n"
            "Всё верно?",
            reply_markup=review_edit_kb(),
        )
        await call.answer()
        return

    await state.set_state(return_state)
    safe = html.escape(generated)
    await edit_text_safe(call, f"Готово ✅ Вернул на шаг ввода.\n\n<code>{safe}</code>")
    await call.answer()
