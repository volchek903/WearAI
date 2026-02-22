from aiogram.fsm.state import State, StatesGroup


class SecondLifeFlow(StatesGroup):
    photo = State()
    confirm = State()
