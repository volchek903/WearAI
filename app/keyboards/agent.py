from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.keyboards.utils import add_button
from app.repository.agent_settings import AgentToggleState


class AgentCallbacks:
    TOGGLE_PREFIX = "agent:toggle:"
    CLEAR_MEMORY = "agent:clear_memory"
    CLEAR_DOCUMENTS = "agent:clear_documents"
    BACK_TO_MENU = "agent:back_to_menu"

    @staticmethod
    def toggle(name: str) -> str:
        return f"{AgentCallbacks.TOGGLE_PREFIX}{name}"


def _state_text(enabled: bool) -> str:
    return "ВКЛ" if enabled else "ВЫКЛ"


def agent_panel_kb(
    settings: AgentToggleState,
    *,
    document_count: int,
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    add_button(
        kb,
        text=f"🌐 Веб-поиск: {_state_text(settings.web_search_enabled)}",
        callback_data=AgentCallbacks.toggle("web_search_enabled"),
    )
    add_button(
        kb,
        text=f"📄 Документы • расширенный режим: {_state_text(settings.documents_enabled)}",
        callback_data=AgentCallbacks.toggle("documents_enabled"),
    )
    add_button(
        kb,
        text=f"🧠 Память • расширенный режим: {_state_text(settings.memory_enabled)}",
        callback_data=AgentCallbacks.toggle("memory_enabled"),
    )
    add_button(
        kb,
        text=f"🔎 Глубокий анализ: {_state_text(settings.deep_analysis_enabled)}",
        callback_data=AgentCallbacks.toggle("deep_analysis_enabled"),
    )
    add_button(
        kb,
        text=f"⚡ Быстрый режим: {_state_text(settings.quick_mode_enabled)}",
        callback_data=AgentCallbacks.toggle("quick_mode_enabled"),
    )
    add_button(
        kb,
        text="🧹 Очистить память",
        callback_data=AgentCallbacks.CLEAR_MEMORY,
        style="danger",
    )
    add_button(
        kb,
        text=f"🗂 Очистить документы ({max(0, int(document_count))})",
        callback_data=AgentCallbacks.CLEAR_DOCUMENTS,
        style="danger",
    )
    add_button(
        kb,
        text="⬅️ В меню",
        callback_data=AgentCallbacks.BACK_TO_MENU,
        style="danger",
    )

    kb.adjust(1, 1, 1, 1, 1, 2, 1)
    return kb.as_markup()
