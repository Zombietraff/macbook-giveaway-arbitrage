"""
Обработчик реферальной системы.

Логика:
1. Кнопка «Пригласить друга» → показать инструкцию + реф-ссылку.
2. Показать количество приглашённых друзей.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from aiogram import F, Router
from aiogram.types import Message

from config import BOT_USERNAME
from db.models import count_completed_referrals, get_user

logger = logging.getLogger(__name__)
router = Router(name="referral")


@router.message(F.text.in_({"👥 Пригласить друга", "👥 Запросити друга"}))
async def show_referral_link(
    message: Message,
    i18n: Callable,
    lang: str,
    **kwargs: Any,
) -> None:
    """Показать реферальную ссылку и статистику приглашений."""
    user_id = message.from_user.id
    db_user = await get_user(user_id)

    if not db_user:
        await message.answer(i18n("start"))
        return

    ref_link = db_user["ref_link"]
    if not ref_link:
        await message.answer(i18n("check_error"))
        return

    # Формируем полную ссылку
    full_ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{ref_link}"

    # Считаем приглашённых
    ref_count = await count_completed_referrals(user_id)

    await message.answer(
        i18n(
            "referral_invite",
            ref_link=full_ref_link,
            ref_count=ref_count,
        ),
    )

    logger.info(
        "User %d запросил реф-ссылку (приглашено: %d)",
        user_id, ref_count,
    )
