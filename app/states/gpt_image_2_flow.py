from aiogram.fsm.state import State, StatesGroup


class GptImage2Flow(StatesGroup):
    photos = State()
    prompt = State()
    settings = State()
