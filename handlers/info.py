"""
Обработчик информационного экрана «Как это работает?».
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from aiogram import F, Router
from aiogram.types import Message

from keyboards.main_menu import get_back_keyboard

logger = logging.getLogger(__name__)
router = Router(name="info")


@router.message(F.text.in_({"ℹ️ Как это работает?", "ℹ️ Як це працює?"}))
async def show_info(
    message: Message,
    i18n: Callable,
    lang: str,
    **kwargs: Any,
) -> None:
    """Показать информацию о механике конкурса."""
    text = f"{i18n('info_title')}\n\n{i18n('info_text')}"

    await message.answer(
        text,
        reply_markup=get_back_keyboard(lang),
    )

    logger.info("User %d открыл экран информации", message.from_user.id)
