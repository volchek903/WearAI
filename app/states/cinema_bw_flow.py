from aiogram.fsm.state import State, StatesGroup


class CinemaBWFlow(StatesGroup):
    female_photo = State()
    male_photo = State()
    confirm = State()
