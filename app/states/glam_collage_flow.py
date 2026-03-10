from aiogram.fsm.state import State, StatesGroup


class GlamCollageFlow(StatesGroup):
    photo = State()
    confirm = State()
