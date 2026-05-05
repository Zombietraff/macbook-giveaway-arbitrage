"""
Клавиатуры главного меню и языка.

Все клавиатуры принимают language_code и возвращают
тексты из файлов локализации.
"""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

import config
from middlewares.localization import get_text
from utils.plugins import get_active_webapp_url


def get_main_menu_keyboard(lang: str = "ru", webapp_url: str | None = None) -> ReplyKeyboardMarkup:
    """
    Главное меню участника (Reply-клавиатура).

    Кнопки:
    - Пригласить друга | Нашёл пасхалку
    - Как это работает? | Профиль
    - Язык | Победители
    - Запустить кампанию
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text=get_text("menu_casino", lang),
                    web_app=WebAppInfo(url=webapp_url or config.WEBAPP_URL),
                ),
            ],
            [
                KeyboardButton(text=get_text("menu_invite", lang)),
                KeyboardButton(text=get_text("menu_promo", lang)),
            ],
            [
                KeyboardButton(text=get_text("menu_info", lang)),
                KeyboardButton(text=get_text("menu_profile", lang)),
            ],
            [
                KeyboardButton(text=get_text("menu_language", lang)),
                KeyboardButton(text=get_text("menu_winners", lang)),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


async def get_active_main_menu_keyboard(lang: str = "ru") -> ReplyKeyboardMarkup:
    """Главное меню с URL активной мини-игры из settings.active_plugin_key."""
    return get_main_menu_keyboard(lang, webapp_url=await get_active_webapp_url())


def get_check_subscription_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """Inline-кнопка «Проверить подписку»."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=get_text("btn_check_subscription", lang),
                    callback_data="check_subscription",
                ),
            ],
        ]
    )


def get_language_keyboard() -> InlineKeyboardMarkup:
    """Inline-кнопки выбора языка."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru"),
                InlineKeyboardButton(text="🇺🇦 Українська", callback_data="lang_uk"),
            ],
        ]
    )


def get_back_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """Inline-кнопка «Назад»."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=get_text("menu_back", lang),
                    callback_data="back_to_menu",
                ),
            ],
        ]
    )


def get_cancel_keyboard(lang: str = "ru") -> ReplyKeyboardMarkup:
    """Reply-кнопка «Отмена» (для FSM-состояний)."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=get_text("menu_cancel", lang))],
        ],
        resize_keyboard=True,
    )
