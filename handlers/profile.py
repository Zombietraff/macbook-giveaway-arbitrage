"""
Обработчик профиля пользователя.

Показывает:
- Telegram ID
- Статус участия
- Количество билетов
- Количество приглашённых друзей
- Premium статус
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from db.models import count_completed_referrals, get_user
from keyboards.main_menu import get_back_keyboard

logger = logging.getLogger(__name__)
router = Router(name="profile")


@router.message(F.text.in_({"👤 Профиль", "👤 Профіль"}))
async def show_profile(
    message: Message,
    i18n: Callable,
    lang: str,
    **kwargs: Any,
) -> None:
    """Показать профиль пользователя."""
    user_id = message.from_user.id
    db_user = await get_user(user_id)

    if not db_user:
        await message.answer(i18n("start"))
        return

    # Статус
    tickets = db_user["tickets"]
    is_active = tickets > 0
    status = i18n("profile_status_active") if is_active else i18n("profile_status_inactive")

    # Premium
    is_premium = db_user["is_premium"]
    premium_text = i18n("profile_premium_yes") if is_premium else i18n("profile_premium_no")

    # Рефералы
    ref_count = await count_completed_referrals(user_id)

    # Собираем текст профиля
    profile_lines = [
        i18n("profile_title"),
        "",
        i18n("profile_id", user_id=user_id),
        i18n("profile_status", status=status),
        i18n("profile_tickets", tickets=int(tickets)),
        i18n("profile_referrals", ref_count=ref_count),
        i18n("profile_premium", premium=premium_text),
    ]

    await message.answer(
        "\n".join(profile_lines),
        reply_markup=get_back_keyboard(lang),
    )

    logger.info("User %d просмотрел профиль (tickets=%.1f)", user_id, tickets)


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(
    callback: CallbackQuery,
    i18n: Callable,
    lang: str,
    **kwargs: Any,
) -> None:
    """Возврат в главное меню по кнопке «Назад»."""
    from keyboards.main_menu import get_main_menu_keyboard

    await callback.message.delete()
    await callback.message.answer(
        "📱",
        reply_markup=get_main_menu_keyboard(lang),
    )
    await callback.answer()
