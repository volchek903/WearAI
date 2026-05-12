from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.core.video_models import VideoModelConfig, VIDEO_MODEL_CATALOG
from app.keyboards.utils import add_button

MENU_BACK_CALLBACK = "menu:back"
MENU_VIDEO_CALLBACK = "menu:video"
MENU_ANIMATE_CALLBACK = "menu:animate"
MENU_MOTION_CONTROL_CALLBACK = "menu:motion_control"


class VideoCallbacks:
    OPEN_PREFIX = "video:open:"
    START_PREFIX = "video:start:"
    SET_PREFIX = "video:set:"
    SKIP_PREFIX = "video:skip:"
    MEDIA_CONTINUE = "video:media:continue"
    CONFIRM = "video:confirm"
    RESTART = "video:restart"

    @staticmethod
    def open(model_id: str) -> str:
        return f"{VideoCallbacks.OPEN_PREFIX}{model_id}"

    @staticmethod
    def start(model_id: str) -> str:
        return f"{VideoCallbacks.START_PREFIX}{model_id}"

    @staticmethod
    def set_value(field: str, value: str) -> str:
        return f"{VideoCallbacks.SET_PREFIX}{field}:{value}"

    @staticmethod
    def skip(field: str) -> str:
        return f"{VideoCallbacks.SKIP_PREFIX}{field}"


def video_models_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for item in VIDEO_MODEL_CATALOG:
        add_button(kb, text=item.title, callback_data=VideoCallbacks.open(item.model_id))
    add_button(
        kb,
        text="⚡ Оживить фото (быстро)",
        callback_data=MENU_ANIMATE_CALLBACK,
    )
    add_button(
        kb,
        text="🎞 Оживить фото по видео",
        callback_data=MENU_MOTION_CONTROL_CALLBACK,
    )
    add_button(kb, text="⬅️ В меню", callback_data=MENU_BACK_CALLBACK, style="danger")
    kb.adjust(1)
    return kb.as_markup()


def video_model_details_kb(model: VideoModelConfig) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(
        kb,
        text="🚀 Начать генерацию",
        callback_data=VideoCallbacks.start(model.model_id),
        style="success",
    )
    add_button(kb, text="⬅️ К моделям", callback_data=MENU_VIDEO_CALLBACK, style="danger")
    kb.adjust(1)
    return kb.as_markup()


def options_kb(
    *,
    field: str,
    options: Sequence[tuple[str, str]],
    back_to_models: bool = False,
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for token, label in options:
        add_button(kb, text=label, callback_data=VideoCallbacks.set_value(field, token))
    if back_to_models:
        add_button(kb, text="⬅️ К моделям", callback_data=MENU_VIDEO_CALLBACK, style="danger")
    kb.adjust(1)
    return kb.as_markup()


def skip_kb(field: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(kb, text="⏭ Пропустить", callback_data=VideoCallbacks.skip(field), style="success")
    kb.adjust(1)
    return kb.as_markup()


def video_media_continue_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(
        kb,
        text="➡️ Продолжить с 1 фото",
        callback_data=VideoCallbacks.MEDIA_CONTINUE,
        style="success",
    )
    add_button(kb, text="🔄 Начать заново", callback_data=VideoCallbacks.RESTART, style="danger")
    kb.adjust(1)
    return kb.as_markup()


def video_confirm_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(kb, text="✅ Запустить", callback_data=VideoCallbacks.CONFIRM, style="success")
    add_button(kb, text="🔄 Начать заново", callback_data=VideoCallbacks.RESTART, style="danger")
    kb.adjust(1)
    return kb.as_markup()
