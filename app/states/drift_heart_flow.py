from aiogram.fsm.state import State, StatesGroup


class DriftHeartFlow(StatesGroup):
    photo = State()
    confirm = State()
