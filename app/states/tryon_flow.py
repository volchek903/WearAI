from aiogram.fsm.state import State, StatesGroup


class TryOnFlow(StatesGroup):
    user_photo = State()  # фото пользователя
    body_part = State()  # выбор части тела кнопками
    item_photo = State()  # фото вещи
    confirm = State()  # подтверждение вещи перед "ХОРОШО"
