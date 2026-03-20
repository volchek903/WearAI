from aiogram.fsm.state import State, StatesGroup


class LegoStyleFlow(StatesGroup):
    photo = State()
    confirm = State()
