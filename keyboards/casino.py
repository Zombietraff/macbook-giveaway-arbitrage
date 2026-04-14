"""
Inline-клавиатуры для модуля «Казик».
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from middlewares.localization import get_text


def get_casino_bets_keyboard(
    available_bets: list[int],
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    """Клавиатура выбора ставки (показывает только доступные ставки)."""
    bet_buttons = [
        InlineKeyboardButton(text=str(bet), callback_data=f"casino_bet_{bet}")
        for bet in available_bets
    ]

    rows: list[list[InlineKeyboardButton]] = []
    if bet_buttons:
        rows.append(bet_buttons)

    rows.append(
        [
            InlineKeyboardButton(
                text=get_text("menu_cancel", lang),
                callback_data="casino_cancel",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_casino_disclaimer_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """Клавиатура подтверждения дисклеймера перед первым входом."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=get_text("casino_disclaimer_btn", lang),
                    callback_data="casino_accept_disclaimer",
                )
            ],
            [
                InlineKeyboardButton(
                    text=get_text("menu_cancel", lang),
                    callback_data="casino_cancel",
                )
            ],
        ]
    )
