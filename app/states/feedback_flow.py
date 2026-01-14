from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class FeedbackFlow(StatesGroup):
    choice = State()  # экран: "всё хорошо / сообщить об ошибке"
    offer_video = State()  # NEW: экран: "сгенерировать видео на основе фото?"
    text = State()  # ввод текста ошибки (если пользователь выбрал BUG)
