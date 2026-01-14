from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

FAQ_BACK_CB = "faq:back"

PRIVACY_URL = "https://telegra.ph/Politika-konfidencialnosti-08-15-17"
TERMS_URL = "https://telegra.ph/Polzovatelskoe-soglashenie-08-15-10"
MANAGER_URL = "https://t.me/WearAIManager"

ARTICLE_GUIDE_URL = "https://telegra.ph/Wear-AI--pochemu-inogda-ne-poluchaetsya-generaciya-foto-i-video-i-kak-sdelat-tak-chtoby-vsyo-rabotalo-stabilno-01-14"
ARTICLE_DONATION_URL = "https://telegra.ph/Wear-AI-popolnenie-i-podpiska-kak-dobrovolnoe-pozhertvovanieTeamATech--Aleksej-01-14"  # NEW


def faq_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    kb.button(text="📘 Как избежать ошибок генерации", url=ARTICLE_GUIDE_URL)
    kb.button(text="💳 Пополнение и подписка", url=ARTICLE_DONATION_URL)  # NEW

    kb.button(text="☑️ Политика конфиденциальности", url=PRIVACY_URL)
    kb.button(text="☑️ Пользовательское соглашение", url=TERMS_URL)
    kb.button(text="💬 Связаться с менеджером", url=MANAGER_URL)
    kb.button(text="⬅️ Назад в меню", callback_data=FAQ_BACK_CB)

    kb.adjust(1)
    return kb.as_markup()
