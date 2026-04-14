from aiogram.fsm.state import State, StatesGroup


class Seedream45Flow(StatesGroup):
    prompt = State()
    settings = State()
    width = State()
    height = State()
