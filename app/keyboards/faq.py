from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.keyboards.utils import add_button

FAQ_BACK_CB = "faq:back"
FAQ_REFERRAL_CB = "faq:referral"

PRIVACY_URL = "https://telegra.ph/Politika-konfidencialnosti-08-15-17"
TERMS_URL = "https://telegra.ph/Polzovatelskoe-soglashenie-08-15-10"
MANAGER_URL = "https://t.me/WearAIManager"

ARTICLE_GUIDE_URL = "https://telegra.ph/Wear-AI--pochemu-inogda-ne-poluchaetsya-generaciya-foto-i-video-i-kak-sdelat-tak-chtoby-vsyo-rabotalo-stabilno-01-14"
ARTICLE_DONATION_URL = "https://telegra.ph/Wear-AI-popolnenie-i-podpiska-kak-dobrovolnoe-pozhertvovanieTeamATech--Aleksej-01-14"


def faq_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    add_button(kb, text="📘 Как избежать ошибок генерации", url=ARTICLE_GUIDE_URL)
    add_button(kb, text="💳 Пополнение и подписка", url=ARTICLE_DONATION_URL)
    add_button(kb, text="🤝 Реферальная система", callback_data=FAQ_REFERRAL_CB)

    add_button(kb, text="🔒 Политика конфиденциальности", url=PRIVACY_URL)
    add_button(kb, text="📄 Пользовательское соглашение", url=TERMS_URL)
    add_button(kb, text="💬 Написать менеджеру", url=MANAGER_URL)
    add_button(kb, text="⬅️ В меню", callback_data=FAQ_BACK_CB, style="danger")

    kb.adjust(1)
    return kb.as_markup()
