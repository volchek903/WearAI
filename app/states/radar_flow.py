from aiogram.fsm.state import State, StatesGroup


class RadarFlow(StatesGroup):
    photos = State()  # фото людей (1–8)
    car = State()  # описание машины
    plates = State()  # номера
    people_action = State()  # что делают люди
    location = State()  # локация
    review = State()  # подтверждение данных
