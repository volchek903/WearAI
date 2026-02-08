from aiogram.fsm.state import State, StatesGroup


class AdminBroadcastFSM(StatesGroup):
    choice = State()
    waiting_content = State()
    confirm = State()
