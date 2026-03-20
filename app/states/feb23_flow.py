from aiogram.fsm.state import State, StatesGroup


class Feb23Flow(StatesGroup):
    photos = State()
    confirm = State()
