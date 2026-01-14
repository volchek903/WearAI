from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InputMediaPhoto
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.menu import MenuCallbacks
from app.keyboards.confirm import yes_no_tryon_kb_with_help, ConfirmCallbacks
from app.keyboards.help import help_button_kb
from app.keyboards.feedback import feedback_kb
from app.repository.users import increment_generated_photos, upsert_user
from app.services.generation import generate_image_kie_from_telegram
from app.services.kie_ai import KieAIError
from app.states.tryon_flow import TryOnFlow
from app.states.feedback_flow import FeedbackFlow
from app.utils.kie_errors import kie_error_to_user_text
from app.utils.tg_edit import edit_text_safe
from app.utils.tg_send import send_image_smart
from app.utils.validators import MAX_TEXT_LEN, is_text_too_long

router = Router()
logger = logging.getLogger(__name__)

TRYON_DESC_EXAMPLE = (
    "Отлично! ✅\n\n"
    "Теперь напиши, <b>что нужно сделать с вещью</b> 👇\n"
    "Примеры:\n"
    "— «Надень эту вещь на меня максимально реалистично»\n"
    "— «Оставь оригинальный цвет/принт/логотип, без лишних объектов»\n"
    "— «Сделай посадку по фигуре, естественные складки, реалистичный свет»"
)


@router.callback_query(F.data == MenuCallbacks.TRYON)
async def start_tryon_flow(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await upsert_user(session, call.from_user.id, call.from_user.username)

    await state.clear()
    await state.set_state(TryOnFlow.user_photo)

    await edit_text_safe(
        call,
        "Поехали! 👕✨\n\nПришли свою фотографию (1 фото) 🤳",
        reply_markup=help_button_kb("user_photo", text="🤳 Как лучше сделать фото?"),
    )
    await call.answer()


@router.message(TryOnFlow.user_photo)
async def user_photo_in(message: Message, state: FSMContext) -> None:
    if message.media_group_id:
        await message.answer("Пожалуйста, пришли одну фотографию (не альбом) 🤳🙂")
        return
    if not message.photo:
        await message.answer(
            "Мне нужна именно фотография 🤳🙂 Пришли, пожалуйста, 1 фото."
        )
        return

    user_file_id = message.photo[-1].file_id
    await state.update_data(user_photo=user_file_id)
    await state.set_state(TryOnFlow.item_photo)

    await message.answer(
        "Фото получил! ✅😊\n\nТеперь пришли фото вещи (1 фото) 📦📸",
        reply_markup=help_button_kb("item_photo", text="📦 Как лучше сфоткать вещь?"),
    )


@router.message(TryOnFlow.item_photo)
async def item_photo_in(message: Message, state: FSMContext) -> None:
    if message.media_group_id:
        await message.answer("Пожалуйста, пришли одно фото вещи (не альбом) 📸🙂")
        return
    if not message.photo:
        await message.answer("Хочу именно фото вещи 📸🙂 Пришли, пожалуйста, 1 фото.")
        return

    item_file_id = message.photo[-1].file_id
    data = await state.get_data()
    user_file_id = data.get("user_photo")

    if not user_file_id:
        await state.clear()
        await message.answer("Ой 😅 Сессия сбилась. Нажми /start и начни заново 🙌")
        return

    await state.update_data(item_photo=item_file_id)
    await state.set_state(TryOnFlow.confirm)

    media = [
        InputMediaPhoto(
            media=user_file_id,
            caption="Смотри 😊\nЭто твоё фото и вещь. Точно надеваем именно её? ✅",
        ),
        InputMediaPhoto(media=item_file_id),
    ]

    try:
        await message.answer_media_group(media=media)
    except Exception:
        await message.answer_photo(user_file_id, caption="Твоё фото 🤳")
        await message.answer_photo(item_file_id, caption="Фото вещи 📦")
        await message.answer("Точно надеваем именно эту вещь? ✅🙂")

    await message.answer(
        "Жду твоё решение 👇🙂", reply_markup=yes_no_tryon_kb_with_help()
    )


@router.callback_query(TryOnFlow.confirm, F.data == ConfirmCallbacks.NO)
async def tryon_choose_other(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(item_photo=None)
    await state.set_state(TryOnFlow.item_photo)

    await edit_text_safe(call, "Ок! 😄 Пришли другое фото вещи (1 фото) 📸")
    await call.answer()


@router.callback_query(TryOnFlow.confirm, F.data == ConfirmCallbacks.YES)
async def tryon_confirmed_go_prompt(call: CallbackQuery, state: FSMContext) -> None:
    # После подтверждения вещи — просим промпт
    await state.set_state(TryOnFlow.tryon_desc)

    await edit_text_safe(
        call,
        TRYON_DESC_EXAMPLE,
        reply_markup=help_button_kb("tryon_desc", text="🪄 Как лучше написать промпт?"),
    )
    await call.answer()


@router.message(TryOnFlow.tryon_desc)
async def tryon_desc_in(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    if not message.text or not message.text.strip():
        await message.answer("Мне нужен текст 🙂 Напиши, что нужно сделать с вещью.")
        return

    style_prompt = message.text.strip()

    if is_text_too_long(style_prompt):
        await message.answer(
            f"Ой 😅 Текст слишком длинный.\n"
            f"Максимум {MAX_TEXT_LEN} символов, а у тебя {len(style_prompt)}.\n"
            "Сократи, пожалуйста, и отправь ещё раз 🙌"
        )
        return

    data = await state.get_data()
    user_photo: str | None = data.get("user_photo")
    item_photo: str | None = data.get("item_photo")

    if not user_photo or not item_photo:
        await state.clear()
        await message.answer("Ой 😅 Сессия сбилась. Нажми /start и начни заново 🙌")
        return

    await message.answer("Делаю примерку… ⏳")

    prompt = (
        "Create a photorealistic virtual try-on result.\n"
        "Use the first image as the person reference (keep face/body identity).\n"
        "Use the second image as the clothing/item reference (keep colors, fabric, prints, logos).\n"
        "Ensure realistic fit, folds, lighting, and proportions. High quality.\n"
        "No extra accessories unless present in the source images.\n"
        f"\nUser instruction (RU): {style_prompt}\n"
    )

    try:
        results = await generate_image_kie_from_telegram(
            bot=message.bot,
            session=session,
            tg_id=message.from_user.id,
            prompt=prompt,
            telegram_photo_file_ids=[user_photo, item_photo],
        )

        if not results:
            raise RuntimeError("KIE returned empty result")

        output_files: list[dict[str, str]] = []
        for filename, img_bytes in results:
            sent = await send_image_smart(
                message, img_bytes=img_bytes, filename=filename
            )

            if getattr(sent, "photo", None):
                output_files.append(
                    {
                        "kind": "photo",
                        "file_id": sent.photo[-1].file_id,
                        "filename": filename,
                    }
                )
            elif getattr(sent, "document", None):
                output_files.append(
                    {
                        "kind": "document",
                        "file_id": sent.document.file_id,
                        "filename": filename,
                    }
                )

        await increment_generated_photos(
            session=session, tg_id=message.from_user.id, delta=1
        )

        await state.set_data(
            {
                "feedback_payload": {
                    "scenario": "tryon",
                    "user_tg_id": message.from_user.id,
                    "username": message.from_user.username or "",
                    "tryon_desc": style_prompt,
                    "kie_prompt": prompt,
                    "input_photos": {
                        "user_photo": user_photo,
                        "item_photo": item_photo,
                    },
                    "output_files": output_files,
                }
            }
        )
        await state.set_state(FeedbackFlow.choice)

        await message.answer(
            "Все получилось как вы хотели или обнаружили ошибку?",
            reply_markup=feedback_kb(),
        )
        return

    except KieAIError as e:
        logger.warning("TRYON KIE failed: %s", e)
        await message.answer(kie_error_to_user_text(e))
        # оставляем в tryon_desc — пусть пользователь сразу поправит промпт и отправит ещё раз
        return

    except Exception as e:
        logger.exception("TRYON generation failed: %s", e)
        await message.answer(
            "Не получилось сделать примерку 😅\n"
            "Попробуй изменить описание и отправь ещё раз."
        )
        return
