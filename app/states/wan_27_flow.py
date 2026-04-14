from aiogram.fsm.state import State, StatesGroup


class Wan27Flow(StatesGroup):
    prompt = State()
    settings = State()
    width = State()
    height = State()
    seed = State()
