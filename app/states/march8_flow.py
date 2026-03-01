from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class March8Flow(StatesGroup):
    photos = State()
    text = State()
    confirm = State()
