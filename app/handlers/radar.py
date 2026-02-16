from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.menu import MenuCallbacks, photo_menu_kb
from app.keyboards.extra import buy_generations_kb
from app.keyboards.confirm import yes_no_kb, ConfirmCallbacks
from app.repository.generations import (
    NoGenerationsLeft,
    charge_photo_generation,
    ensure_default_subscription,
    refund_photo_generation,
)
from app.repository.users import increment_generated_photos, upsert_user
from app.services.album_collector import AlbumCollector
from app.services.generation import generate_image_kie_from_telegram
from app.services.kie_ai import KieAIError
from app.states.radar_flow import RadarFlow
from app.utils.kie_errors import kie_error_to_user_text
from app.utils.progress_bar import progress_initial_text, progress_loop, stop_progress
from app.utils.tg_edit import edit_text_safe
from app.utils.content_media import send_content_photo
from app.utils.tg_send import send_image_smart
from app.utils.validators import MAX_TEXT_LEN, is_text_too_long

router = Router()
logger = logging.getLogger(__name__)
_album = AlbumCollector(debounce_seconds=0.8)

RADAR_BASE_PROMPT = (
    "Ультрареалистичная фотография с камеры наблюдения за дорожным движением на "
    "обочине, аутентичные кадры автоматического контроля скорости.\n\n"
    "Сцена:\n"
    "Черно-белое изображение, случайно снятое стационарной придорожной камерой "
    "контроля скорости.\n"
    "Современный седан движется по многополосной городской дороге.\n"
    "В открытом люке на крыше стоит молодая женщина, верхняя часть тела которой "
    "находится снаружи автомобиля.\n"
    "Она слегка улыбается и делает неприличный жест рукой в сторону камеры.\n"
    "Внутри автомобиля через лобовое стекло видна другая девушка-водитель, "
    "которая спокойно ведет машину и улыбается.\n"
    "Эффект зернистости.\n"
    "Сжатие в формате JPEG.\n\n"
    "Предметы:\n"
    "• Женщина-пассажир: волосы распущены, выражение лица непринужденное.\n"
    "Она высовывается из люка, облокотившись на край крыши.\n"
    "• Водитель-женщина: расслабленное лицо, легкая улыбка, обе руки на руле.\n\n"
    "Перенесите лица с фотографии, которую я загрузил, не меняйте их, но "
    "адаптируйте к освещению и стилю новой фотографии. используйте 100% "
    "загруженное лицо.\n\n"
    "Машина:\n"
    "Mercedes SL63 AMG 2023 купе\n"
    "Темный цвет кузова, в черно-белом исполнении выглядит как темно-серый.\n"
    "Хорошо видна агрессивная решетка радиатора.\n"
    "Российский номерной знак в стандартном формате “К777ИС777” слегка размыт, "
    "но читаем.\n"
    "Капот, фары, лобовое стекло и крыша полностью видны.\n\n"
    "Камера и композиция:\n"
    "Широкоугольный снимок с камеры наблюдения за соблюдением правил дорожного "
    "движения, установленной над дорогой.\n"
    "Вид сверху и немного впереди автомобиля.\n"
    "Автомобиль занимает большую часть кадра.\n"
    "Вокруг автомобиля видна дорожная разметка (полосы движения).\n"
    "Отражения от лобового стекла резкие, но реалистичные.\n"
    "Размытие при движении получается тонким и естественным.\n\n"
    "Визуальный стиль:\n"
    "Строгое черно-белое изображение.\n"
    "Аутентичный вид российских камер видеонаблюдения.\n"
    "Высокая контрастность, заметная зернистость пленки и цифровой шум.\n"
    "Ровное дневное освещение, отсутствие драматических теней.\n"
    "Нет кинематографической глубины резкости.\n"
    "Никакой стилизации, никакого художественного оформления.\n\n"
    "Наложение текста:\n"
    "Техническое наложение камеры в нижней части рамки.\n"
    "Моноширинный системный шрифт.\n"
    "Русский язык.\n"
    "Включает в себя:\n"
    "• системный идентификатор\n"
    "• значение скорости в км/ч\n"
    "• дата и время\n"
    "• GPS-координаты\n"
    "• описание местоположения\n"
    "Текст выглядит слегка сжатым и несовершенным, как будто выжженным в "
    "видеоматериале.\n\n"
    "Ограничения:\n"
    "Никакого студийного освещения.\n"
    "Никакой модной фотосъемки.\n"
    "Никаких кинематографических кадров.\n"
    "Никаких преувеличений.\n"
)


@router.callback_query(F.data == MenuCallbacks.RADAR)
async def radar_entry(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await call.answer()
    await upsert_user(session, call.from_user.id, call.from_user.username)
    await state.clear()
    await state.set_state(RadarFlow.photos)

    if call.message:
        try:
            await call.message.delete()
        except Exception:
            pass
        await send_content_photo(
            call.message,
            filename="radar.jpg",
            caption=(
                "🛰 <b>ИИ Радар</b>\n\n"
                "Пришли фото людей, которые будут в кадре.\n"
                "Можно 1–8 фото одним сообщением (альбомом) 📸"
            ),
            parse_mode="HTML",
        )


@router.message(RadarFlow.photos)
async def radar_photos_in(message: Message, state: FSMContext) -> None:
    if not message.photo:
        await message.answer(
            "Нужно отправить <b>от 1 до 8 фото</b> одним сообщением (альбомом) 📸"
        )
        return

    if not message.media_group_id:
        file_id = message.photo[-1].file_id
        await state.update_data(photos=[file_id])
        await state.set_state(RadarFlow.car)
        await message.answer("Опиши, какая машина должна быть на фото ✍️")
        return

    await _album.push(
        message.chat.id, message.media_group_id, message.photo[-1].file_id
    )
    result = await _album.collect(message.chat.id, message.media_group_id)
    if not result.file_ids:
        return

    if not (1 <= len(result.file_ids) <= 8):
        await message.answer(
            "Ой, тут должно быть <b>от 1 до 8 фото</b> одним сообщением. "
            "Попробуй ещё раз 📸"
        )
        return

    await state.update_data(photos=result.file_ids)
    await state.set_state(RadarFlow.car)
    await message.answer("Опиши, какая машина должна быть на фото ✍️")


@router.message(RadarFlow.car)
async def radar_car_in(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Нужен текст ✍️ Опиши машину.")
        return
    if is_text_too_long(text):
        await message.answer(
            f"Ой, текст слишком длинный 😅\n"
            f"Максимум {MAX_TEXT_LEN} символов, а у тебя {len(text)}.\n"
            "Сократи, пожалуйста, и отправь ещё раз 🙌"
        )
        return
    await state.update_data(car=text)
    await state.set_state(RadarFlow.plates)
    await message.answer("Напиши номер машины ✍️")


@router.message(RadarFlow.plates)
async def radar_plates_in(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Нужен текст ✍️ Напиши номер машины.")
        return
    if is_text_too_long(text):
        await message.answer(
            f"Ой, текст слишком длинный 😅\n"
            f"Максимум {MAX_TEXT_LEN} символов, а у тебя {len(text)}.\n"
            "Сократи, пожалуйста, и отправь ещё раз 🙌"
        )
        return
    await state.update_data(plates=text)
    await state.set_state(RadarFlow.people_action)
    await message.answer("Опиши, что делают люди в машине ✍️")


@router.message(RadarFlow.people_action)
async def radar_people_action_in(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Нужен текст ✍️ Опиши, что делают люди.")
        return
    if is_text_too_long(text):
        await message.answer(
            f"Ой, текст слишком длинный 😅\n"
            f"Максимум {MAX_TEXT_LEN} символов, а у тебя {len(text)}.\n"
            "Сократи, пожалуйста, и отправь ещё раз 🙌"
        )
        return
    await state.update_data(people_action=text)
    await state.set_state(RadarFlow.location)
    await message.answer("Напиши адрес где сфоткал радар, чем точнее тем лучше ✍️")


@router.message(RadarFlow.location)
async def radar_location_in(
    message: Message, state: FSMContext
) -> None:
    location = (message.text or "").strip()
    if not location:
        await message.answer("Нужен текст ✍️ Опиши локацию.")
        return
    if is_text_too_long(location):
        await message.answer(
            f"Ой, текст слишком длинный 😅\n"
            f"Максимум {MAX_TEXT_LEN} символов, а у тебя {len(location)}.\n"
            "Сократи, пожалуйста, и отправь ещё раз 🙌"
        )
        return

    await state.update_data(location=location)
    data = await state.get_data()
    await state.set_state(RadarFlow.review)

    summary = (
        "Проверь данные ✅\n\n"
        f"Машина: {data.get('car')}\n"
        f"Номер: {data.get('plates')}\n"
        f"Действия людей: {data.get('people_action')}\n"
        f"Локация: {data.get('location')}\n\n"
        "Всё верно?"
    )
    await message.answer(summary, reply_markup=yes_no_kb(yes_text="✅ Да", no_text="✏️ Изменить"))


@router.callback_query(RadarFlow.review, F.data == ConfirmCallbacks.NO)
async def radar_review_edit(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.update_data(
        photos=[],
        car="",
        plates="",
        people_action="",
        location="",
    )
    await state.set_state(RadarFlow.photos)
    await edit_text_safe(
        call,
        "Окей! Пришли фото людей, которые будут в кадре.\n"
        "Можно 1–8 фото одним сообщением (альбомом) 📸",
    )


@router.callback_query(RadarFlow.review, F.data == ConfirmCallbacks.YES)
async def radar_review_confirm(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await call.answer()
    data = await state.get_data()
    photos = data.get("photos") or []
    car = (data.get("car") or "").strip()
    plates = (data.get("plates") or "").strip()
    people_action = (data.get("people_action") or "").strip()
    location = (data.get("location") or "").strip()

    if not photos or not car or not plates or not people_action or not location:
        await state.clear()
        await edit_text_safe(
            call, "Ой, сессия сбилась 😅 Нажми /start и начни заново 🙌"
        )
        return

    progress_msg = await call.message.answer(progress_initial_text())
    stop = asyncio.Event()

    async def _update(text: str) -> None:
        try:
            await progress_msg.edit_text(text)
        except Exception:
            return

    progress_task = asyncio.create_task(progress_loop(_update, stop))

    await upsert_user(session, call.from_user.id, call.from_user.username)
    tg_id = call.from_user.id
    await ensure_default_subscription(session, tg_id)

    try:
        await charge_photo_generation(session, tg_id)
    except NoGenerationsLeft:
        await stop_progress(stop, progress_task)
        await edit_text_safe(
            progress_msg,
            "⛔️ Лимит генераций исчерпан.\n\nОформи подписку или пополни баланс 💳",
            reply_markup=buy_generations_kb(),
        )
        await state.clear()
        return

    prompt = (
        f"{RADAR_BASE_PROMPT}\n"
        "Детали от пользователя:\n"
        f"Машина: {car}\n"
        f"Номер: {plates}\n"
        f"Действия людей: {people_action}\n"
        f"Локация: {location}\n"
        "Лица должны быть детально прорисованы на основе фотографий пользователя.\n"
    )

    sent_any = False
    try:
        results = await generate_image_kie_from_telegram(
            bot=call.bot,
            session=session,
            tg_id=tg_id,
            prompt=prompt,
            telegram_photo_file_ids=photos,
            max_images=8,
        )
        if not results:
            raise RuntimeError("KIE returned empty result")

        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, "✅ Готово! Отправляю результат…")

        for filename, img_bytes in results:
            await send_image_smart(call.message, img_bytes=img_bytes, filename=filename)
            sent_any = True

        await increment_generated_photos(session=session, tg_id=tg_id, delta=1)
        await state.clear()
        await call.message.answer(
            "Хотите ли что-то ещё сгенерировать?",
            reply_markup=photo_menu_kb(),
        )
        return

    except KieAIError as e:
        logger.warning("RADAR KIE failed: %s", e)
        if not sent_any:
            await refund_photo_generation(session, tg_id)
        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, kie_error_to_user_text(e))
        await state.clear()
        return

    except Exception as e:
        logger.exception("RADAR generation failed: %s", e)
        if not sent_any:
            await refund_photo_generation(session, tg_id)
        await stop_progress(stop, progress_task)
        await edit_text_safe(
            progress_msg,
            "Не получилось сгенерировать 😅\nПопробуй ещё раз чуть позже.",
        )
        await state.clear()
        return
