from aiogram.fsm.state import State, StatesGroup


class AdminAccessFSM(StatesGroup):
    waiting_user_id = State()
