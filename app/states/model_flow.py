from aiogram.fsm.state import State, StatesGroup


class ModelFlow(StatesGroup):
    model_desc = State()  # пользователь описывает модель
    confirm_model_desc = State()  # подтверждает описание модели
    product_photos = State()  # отправляет 1–5 фото товара
    presentation_desc = State()  # описывает, как преподнести товар
    review = State()  # итоговая проверка перед "ОТЛИЧНО"
