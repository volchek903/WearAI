from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AnimatePhotoStates(StatesGroup):
    waiting_photo = State()
    waiting_prompt = State()
