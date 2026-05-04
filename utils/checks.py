"""
Утилиты проверок: валидация языка, ID, подписки на каналы.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
)

from config import BLACKLIST_LANG, MAX_USER_ID
from db.models import get_all_channels

logger = logging.getLogger(__name__)

# Допустимые статусы подписки
_SUBSCRIBED_STATUSES = frozenset({"member", "administrator", "creator"})


def is_valid_language(language_code: Optional[str]) -> bool:
    """
    Проверить, что язык пользователя НЕ в чёрном списке.

    Args:
        language_code: Telegram language_code пользователя.

    Returns:
        True — язык допустим, False — заблокирован.
    """
    if not language_code:
        return True  # Нет языка → пропускаем
    # Берём первые 2 символа (например, 'zh-hans' → 'zh')
    lang_prefix = language_code.lower()[:2]
    return lang_prefix not in BLACKLIST_LANG


def is_valid_user_id(user_id: int) -> bool:
    """Проверить, что Telegram user_id не выше системного порога."""
    return int(user_id) <= MAX_USER_ID




async def check_subscription(
    bot: Bot,
    user_id: int,
    max_retries: int = 3,
) -> tuple[bool, list[dict]]:
    """
    Проверить подписку пользователя на все обязательные каналы.

    Args:
        bot: экземпляр бота.
        user_id: Telegram ID пользователя.
        max_retries: максимальное число попыток при ошибках сети.

    Returns:
        Кортеж (all_subscribed: bool, unsubscribed_channels: list[dict]).
        Каждый элемент unsubscribed_channels — dict с ключами
        channel_id, title, invite_link.
    """
    channels = await get_all_channels()

    if not channels:
        # Нет каналов в БД → считаем подписку успешной
        logger.warning("Нет каналов в БД для проверки подписки.")
        return True, []

    unsubscribed: list[dict] = []

    for ch in channels:
        channel_id = ch["channel_id"]
        title = ch["title"]
        invite_link = ch["invite_link"]

        subscribed = await _check_single_channel(
            bot, channel_id, user_id, max_retries
        )

        if not subscribed:
            unsubscribed.append({
                "channel_id": channel_id,
                "title": title,
                "invite_link": invite_link,
            })

    all_subscribed = len(unsubscribed) == 0
    return all_subscribed, unsubscribed


async def _check_single_channel(
    bot: Bot,
    channel_id: str,
    user_id: int,
    max_retries: int = 3,
) -> bool:
    """
    Проверить подписку на один канал с обработкой ошибок API.

    Реализует экспоненциальную задержку при RetryAfter/429.
    """
    for attempt in range(1, max_retries + 1):
        try:
            member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            return member.status in _SUBSCRIBED_STATUSES

        except TelegramRetryAfter as e:
            wait_time = e.retry_after + 1
            logger.warning(
                "RetryAfter при проверке канала %s (user %d): ждём %d сек (попытка %d/%d)",
                channel_id, user_id, wait_time, attempt, max_retries,
            )
            await asyncio.sleep(wait_time)

        except TelegramForbiddenError:
            logger.error(
                "Бот забанен/кикнут из канала %s. Пропускаем проверку.",
                channel_id,
            )
            # Если бот кикнут — не блокируем пользователя
            return True

        except (TelegramBadRequest, TelegramNotFound) as e:
            logger.error(
                "Ошибка API при проверке канала %s (user %d): %s",
                channel_id, user_id, e,
            )
            return False

        except Exception as e:
            backoff = 2 ** attempt
            logger.warning(
                "Ошибка сети при проверке канала %s (user %d): %s. "
                "Повтор через %d сек (попытка %d/%d)",
                channel_id, user_id, e, backoff, attempt, max_retries,
            )
            if attempt < max_retries:
                await asyncio.sleep(backoff)

    logger.error(
        "Исчерпаны попытки проверки канала %s для user %d.",
        channel_id, user_id,
    )
    return False
