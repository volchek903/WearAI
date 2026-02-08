from aiogram.fsm.state import State, StatesGroup


class NanoBananaFlow(StatesGroup):
    photos = State()  # пользователь отправляет 1–8 фото
    prompt = State()  # пользователь отправляет промпт
