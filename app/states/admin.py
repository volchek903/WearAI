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


class AdminPackagesFSM(StatesGroup):
    waiting_value = State()
    confirm = State()


class AdminPackageCreateFSM(StatesGroup):
    name = State()
    duration_days = State()
    photo_generations = State()
    video_generations = State()
    price = State()
    stars_price = State()
    confirm = State()


class AdminLaunchLimitFSM(StatesGroup):
    waiting_value = State()


class AdminModelPricingFSM(StatesGroup):
    waiting_value = State()
