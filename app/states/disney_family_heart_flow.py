from aiogram.fsm.state import State, StatesGroup


class DisneyFamilyHeartFlow(StatesGroup):
    photos = State()
    confirm = State()
