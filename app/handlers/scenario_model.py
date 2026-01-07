from __future__ import annotations

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession
from app.utils.validators import MAX_TEXT_LEN, is_text_too_long

from app.keyboards.menu import MenuCallbacks
from app.keyboards.confirm import yes_no_kb, review_edit_kb, ConfirmCallbacks
from app.keyboards.help import help_button_kb
from app.repository.users import increment_generated_photos, upsert_user
from app.services.album_collector import AlbumCollector
from app.states.model_flow import ModelFlow
from app.utils.tg_edit import edit_text_safe

router = Router()
_album = AlbumCollector(debounce_seconds=0.8)

MODEL_DESC_EXAMPLE = (
    "Отлично! 🛍✨\n\n"
    "Опиши, какой ты хочешь видеть модель 👇\n"
    "Пример: “Девушка 22–25 лет, натуральный макияж, студийный свет, белый фон, стиль casual, "
    "лёгкая улыбка, поза в пол-оборота”."
)

PRESENTATION_EXAMPLE = (
    "Класс, фото получил! ✅\n\n"
    "Теперь напиши, <b>как модель должна показать товар</b> 👇\n"
    "Примеры:\n"
    "— “Это кольцо должно быть на пальце правой руки, крупный план.”\n"
    "— “Эти серьги должны быть на ушах, портрет по плечи.”\n"
    "— “Эта вещь должна быть на ногтях, макро-кадр.”"
)


@router.callback_query(F.data == MenuCallbacks.MODEL)
async def start_model_flow(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await upsert_user(session, call.from_user.id, call.from_user.username)

    await state.clear()
    await state.set_state(ModelFlow.model_desc)

    await edit_text_safe(
        call, MODEL_DESC_EXAMPLE, reply_markup=help_button_kb("model_desc")
    )
    await call.answer()


@router.message(ModelFlow.model_desc)
async def model_desc_in(message: Message, state: FSMContext) -> None:
    if not message.text or not message.text.strip():
        await message.answer(
            "Ой 😅 Мне нужен текст. Опиши модель словами, пожалуйста 🙌"
        )
        return

    desc = message.text.strip()

    if is_text_too_long(desc):
        await message.answer(
            f"Ой 😅 Текст слишком длинный.\n"
            f"Максимум {MAX_TEXT_LEN} символов, а у тебя {len(desc)}.\n"
            "Сократи, пожалуйста, и отправь ещё раз 🙌"
        )
        return

    await state.update_data(model_desc=desc)
    await state.set_state(ModelFlow.confirm_model_desc)

    await message.answer(
        f"Супер! 😊 Вот так я понял твою модель:\n“{desc}”\n\nВсё верно? ✅",
        reply_markup=yes_no_kb(yes_text="✅ Да", no_text="✏️ Изменить"),
    )


@router.callback_query(ModelFlow.confirm_model_desc, F.data == ConfirmCallbacks.NO)
async def model_desc_edit(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ModelFlow.model_desc)

    await edit_text_safe(
        call,
        "Ок! 😄 Тогда опиши модель заново 👇\n\n"
        + MODEL_DESC_EXAMPLE.split("\n\n", 1)[1],
        reply_markup=help_button_kb("model_desc"),
    )
    await call.answer()


@router.callback_query(ModelFlow.confirm_model_desc, F.data == ConfirmCallbacks.YES)
async def model_desc_confirmed(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ModelFlow.product_photos)

    await edit_text_safe(
        call,
        "Отлично! Теперь пришли фото товара 📸\n"
        "Можно от 1 до 5 фото за один раз (одним сообщением/альбомом) 🙌",
        reply_markup=help_button_kb("product_photos", text="📸 Как лучше сфоткать?"),
    )
    await call.answer()


@router.message(ModelFlow.product_photos)
async def product_photos_in(message: Message, state: FSMContext) -> None:
    if not message.photo:
        await message.answer(
            "Ой, кажется, это не то 😅\n"
            "Нужно отправить <b>от 1 до 5 фото</b> товара одним сообщением (альбомом) 📸\n"
            "Попробуй ещё раз 🙌"
        )
        return

    # одиночное фото — разрешаем
    if not message.media_group_id:
        file_id = message.photo[-1].file_id
        await state.update_data(product_photos=[file_id])
        await state.set_state(ModelFlow.presentation_desc)
        await message.answer(
            PRESENTATION_EXAMPLE, reply_markup=help_button_kb("presentation_desc")
        )
        return

    # альбом — собираем
    await _album.push(
        message.chat.id, message.media_group_id, message.photo[-1].file_id
    )
    result = await _album.collect(message.chat.id, message.media_group_id)

    if not result.file_ids:
        return

    if not (1 <= len(result.file_ids) <= 5):
        await message.answer(
            "Ой 😅 Тут должно быть <b>от 1 до 5 фото</b> одним сообщением. Попробуй ещё раз 📸🙌"
        )
        return

    await state.update_data(product_photos=result.file_ids)
    await state.set_state(ModelFlow.presentation_desc)
    await message.answer(
        PRESENTATION_EXAMPLE, reply_markup=help_button_kb("presentation_desc")
    )


@router.message(ModelFlow.presentation_desc)
async def presentation_desc_in(message: Message, state: FSMContext) -> None:
    if not message.text or not message.text.strip():
        await message.answer(
            "Мне нужен текст 😊 Опиши, пожалуйста, как показываем товар 👇"
        )
        return

    pres = message.text.strip()

    if is_text_too_long(pres):
        await message.answer(
            f"Ой 😅 Текст слишком длинный.\n"
            f"Максимум {MAX_TEXT_LEN} символов, а у тебя {len(pres)}.\n"
            "Сократи, пожалуйста, и отправь ещё раз 🙌"
        )
        return

    await state.update_data(presentation_desc=pres)
    await state.set_state(ModelFlow.review)

    data = await state.get_data()
    desc = data.get("model_desc", "")
    photos = data.get("product_photos", []) or []

    await message.answer(
        "Давай быстренько проверим ✅😊\n\n"
        f"1) Описание модели: “{desc}”\n"
        f"2) Фото товара: {len(photos)} шт. 📸\n"
        f"3) Подача товара: “{pres}”\n\n"
        "Всё верно?",
        reply_markup=review_edit_kb(),
    )


@router.callback_query(ModelFlow.review, F.data == ConfirmCallbacks.EDIT_MODEL)
async def review_edit_model(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ModelFlow.model_desc)

    await edit_text_safe(
        call,
        "Ок! 😄 Меняем описание модели 👇\n\n" + MODEL_DESC_EXAMPLE.split("\n\n", 1)[1],
        reply_markup=help_button_kb("model_desc"),
    )
    await call.answer()


@router.callback_query(ModelFlow.review, F.data == ConfirmCallbacks.EDIT_PHOTOS)
async def review_edit_photos(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ModelFlow.product_photos)

    await edit_text_safe(
        call,
        "Ок! 😄 Пришли фото товара заново (1–5 фото одним сообщением) 📸",
        reply_markup=help_button_kb("product_photos", text="📸 Как лучше сфоткать?"),
    )
    await call.answer()


@router.callback_query(ModelFlow.review, F.data == ConfirmCallbacks.EDIT_PRESENTATION)
async def review_edit_presentation(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ModelFlow.presentation_desc)

    await edit_text_safe(
        call,
        "Ок! 😊 Напиши подачу товара заново 👇\n\n" + PRESENTATION_EXAMPLE,
        reply_markup=help_button_kb("presentation_desc"),
    )
    await call.answer()


@router.callback_query(ModelFlow.review, F.data == ConfirmCallbacks.YES)
async def review_confirmed(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await increment_generated_photos(session=session, tg_id=call.from_user.id, delta=1)
    await state.clear()

    await edit_text_safe(call, "ОТЛИЧНО ✅😎")
    await call.answer()
