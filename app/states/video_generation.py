from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class VideoGenerationFlow(StatesGroup):
    media = State()
    prompt = State()
    negative_prompt = State()
    duration = State()
    resolution = State()
    aspect_ratio = State()
    sound = State()
    generate_audio = State()
    web_search = State()
    cfg_scale = State()
    shot_type = State()
    seed = State()
    confirm = State()
