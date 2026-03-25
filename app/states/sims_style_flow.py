from aiogram.fsm.state import State, StatesGroup


class SimsStyleFlow(StatesGroup):
    photo = State()
    confirm = State()
