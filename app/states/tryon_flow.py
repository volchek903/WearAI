from aiogram.fsm.state import State, StatesGroup


class TryOnFlow(StatesGroup):
    user_photo = State()  # фото пользователя
    item_photo = State()  # фото вещи
    confirm = State()  # подтверждение вещи
    tryon_desc = State()  # текст: что сделать с вещью (промпт)
