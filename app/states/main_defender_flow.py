from aiogram.fsm.state import State, StatesGroup


class MainDefenderFlow(StatesGroup):
    photos = State()
    confirm = State()
