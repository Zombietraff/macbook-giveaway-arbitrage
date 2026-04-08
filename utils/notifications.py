"""
Уведомления пользователей.

Обработка ошибок отправки (BotBlocked, пользователь удалил чат и т.д.).
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
)

from db.models import set_user_blocked
from middlewares.localization import get_text

logger = logging.getLogger(__name__)


async def notify_referrer(
    bot: Bot,
    referrer_id: int,
    referred_username: str,
    referrer_total_tickets: float,
    lang: str = "ru",
) -> bool:
    """
    Отправить уведомление рефереру о новом реферале.

    Args:
        bot: экземпляр бота.
        referrer_id: Telegram ID реферера.
        referred_username: имя/username приглашённого.
        referrer_total_tickets: текущее кол-во билетов реферера.
        lang: язык реферера.

    Returns:
        True если сообщение доставлено, False если нет.
    """
    text = get_text(
        "referral_success",
        lang,
        username=referred_username,
        total=int(referrer_total_tickets),
    )

    return await _safe_send_message(bot, referrer_id, text)


async def notify_winner(
    bot: Bot,
    user_id: int,
    prize: str,
    lang: str = "ru",
) -> bool:
    """
    Отправить уведомление победителю розыгрыша.

    Args:
        bot: экземпляр бота.
        user_id: Telegram ID победителя.
        prize: название приза.
        lang: язык пользователя.

    Returns:
        True если сообщение доставлено, False если нет.
    """
    text = get_text("winners_entry", lang, place="🏆", name="Приз", prize=prize)
    return await _safe_send_message(bot, user_id, text)


async def _safe_send_message(
    bot: Bot,
    user_id: int,
    text: str,
) -> bool:
    """
    Безопасная отправка сообщения с обработкой ошибок.

    При TelegramForbiddenError (бот заблокирован) устанавливает
    blocked_bot=True в БД.

    Returns:
        True если доставлено, False если нет.
    """
    try:
        await bot.send_message(chat_id=user_id, text=text)
        return True

    except TelegramForbiddenError:
        logger.warning(
            "Пользователь %d заблокировал бота. Установлен blocked_bot=True.",
            user_id,
        )
        await set_user_blocked(user_id, blocked=True)
        return False

    except (TelegramBadRequest, TelegramNotFound) as e:
        logger.warning(
            "Не удалось отправить сообщение user=%d: %s",
            user_id, e,
        )
        return False

    except Exception as e:
        logger.error(
            "Неожиданная ошибка при отправке сообщения user=%d: %s",
            user_id, e,
        )
        return False
