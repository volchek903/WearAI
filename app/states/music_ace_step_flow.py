from aiogram.fsm.state import State, StatesGroup


class MusicAceStepFlow(StatesGroup):
    tags = State()
    structure = State()
    custom_structure = State()
    section_text = State()
    duration = State()
    confirm = State()
