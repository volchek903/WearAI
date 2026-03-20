from aiogram.fsm.state import State, StatesGroup


class MotionControlFlow(StatesGroup):
    photo = State()
    video = State()
    prompt = State()
    confirm = State()
