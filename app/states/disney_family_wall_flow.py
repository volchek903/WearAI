from aiogram.fsm.state import State, StatesGroup


class DisneyFamilyWallFlow(StatesGroup):
    photos = State()
    confirm = State()
