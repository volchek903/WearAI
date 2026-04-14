from aiogram.fsm.state import State, StatesGroup


class SeedreamFlow(StatesGroup):
    prompt = State()
    references = State()
    settings = State()
    width = State()
    height = State()
