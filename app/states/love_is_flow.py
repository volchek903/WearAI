from aiogram.fsm.state import State, StatesGroup


class LoveIsFlow(StatesGroup):
    photos = State()
    text = State()
    ready = State()
