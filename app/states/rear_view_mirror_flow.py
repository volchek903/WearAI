from aiogram.fsm.state import State, StatesGroup


class RearViewMirrorFlow(StatesGroup):
    photo = State()
    confirm = State()
