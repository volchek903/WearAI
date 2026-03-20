from aiogram.fsm.state import State, StatesGroup


class CarInHandFlow(StatesGroup):
    photo = State()
    background = State()
    hand = State()
