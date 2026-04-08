"""
Обработчик команды /winners — показ победителей розыгрыша.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from db.models import get_all_winners

logger = logging.getLogger(__name__)
router = Router(name="winners")


@router.message(Command("winners"))
@router.message(F.text.in_({"🏆 Победители", "🏆 Переможці"}))
async def show_winners(
    message: Message,
    i18n: Callable,
    lang: str,
    **kwargs: Any,
) -> None:
    """Показать список победителей розыгрыша."""
    winners = await get_all_winners()

    if not winners:
        await message.answer(i18n("winners_empty"))
        return

    lines = [i18n("winners_title"), ""]
    for idx, w in enumerate(winners, 1):
        name = w["username"] or w["first_name"] or f"User {w['user_id']}"
        if w["username"]:
            name = f"@{name}"
        lines.append(
            i18n("winners_entry", place=idx, name=name, prize=w["prize"]),
        )

    await message.answer("\n".join(lines))
    logger.info("User %d просмотрел победителей", message.from_user.id)
