from aiogram.fsm.state import State, StatesGroup


class AdminAccessFSM(StatesGroup):
    waiting_user_id = State()


class AdminPromoFSM(StatesGroup):
    code = State()
    kind = State()
    photo_count = State()
    video_count = State()
    max_uses = State()
    confirm = State()
