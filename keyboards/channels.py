"""
Inline-клавиатуры со ссылками на каналы для подписки.
"""

from __future__ import annotations

from typing import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from middlewares.localization import get_text


def get_channels_keyboard(
    channels: Sequence,
    lang: str = "ru",
    unsubscribed_only: bool = False,
    unsubscribed_ids: set[str] | None = None,
) -> InlineKeyboardMarkup:
    """
    Inline-клавиатура со ссылками на каналы.

    Args:
        channels: список строк из таблицы channels (Row objects).
        lang: код языка.
        unsubscribed_only: показывать только каналы без подписки.
        unsubscribed_ids: set channel_id на которые не подписан.

    Returns:
        InlineKeyboardMarkup с кнопками-ссылками на каналы
        и кнопкой «Проверить подписку» внизу.
    """
    buttons: list[list[InlineKeyboardButton]] = []

    for ch in channels:
        channel_id = ch["channel_id"]
        title = ch["title"]
        invite_link = ch["invite_link"]

        if unsubscribed_only and unsubscribed_ids and channel_id not in unsubscribed_ids:
            continue

        buttons.append([
            InlineKeyboardButton(
                text=f"📢 {title}",
                url=invite_link,
            )
        ])

    # Кнопка «Проверить подписку» внизу
    buttons.append([
        InlineKeyboardButton(
            text=get_text("btn_check_subscription", lang),
            callback_data="check_subscription",
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)
