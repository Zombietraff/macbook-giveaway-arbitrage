"""
Глобальная проверка обязательных подписок.

Блокирует действия зарегистрированных пользователей, если они отписались
от одного или нескольких обязательных каналов.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict

from aiogram import BaseMiddleware, Bot
from aiogram.types import CallbackQuery, Message, TelegramObject

from db.models import get_user
from keyboards.channels import get_channels_keyboard
from middlewares.localization import get_text
from utils.admin_access import is_admin
from utils.checks import check_subscription

logger = logging.getLogger(__name__)

_ALLOWED_MESSAGE_TEXTS = frozenset({
    "🌐 Язык",
    "🌐 Мова",
})

_ALLOWED_CALLBACK_DATA = frozenset({
    "check_subscription",
    "lang_ru",
    "lang_uk",
})


def _message_command(text: str) -> str:
    """Вернуть команду без аргументов и bot username."""
    command = text.strip().split(maxsplit=1)[0] if text else ""
    return command.split("@", maxsplit=1)[0]


def _is_allowed_message(message: Message) -> bool:
    text = (message.text or "").strip()
    if not text:
        return False
    return text in _ALLOWED_MESSAGE_TEXTS


def _is_allowed_callback(callback: CallbackQuery) -> bool:
    return (callback.data or "") in _ALLOWED_CALLBACK_DATA


async def _send_subscription_required(
    event: Message | CallbackQuery,
    lang: str,
    i18n: Callable[..., str],
    unsubscribed: list[dict],
) -> None:
    unsubscribed_ids = {channel["channel_id"] for channel in unsubscribed}
    reply_markup = get_channels_keyboard(
        unsubscribed,
        lang=lang,
        unsubscribed_only=True,
        unsubscribed_ids=unsubscribed_ids,
    )

    if isinstance(event, Message):
        await event.answer(i18n("not_subscribed"), reply_markup=reply_markup)
        return

    if isinstance(event.message, Message):
        await event.message.answer(i18n("not_subscribed"), reply_markup=reply_markup)
        await event.answer()
        return

    await event.answer(i18n("not_subscribed"), show_alert=True)


class SubscriptionMiddleware(BaseMiddleware):
    """
    Middleware: проверяет подписки на каждом пользовательском действии.

    Исключения: незарегистрированные пользователи, админы, смена языка
    и ручная кнопка проверки подписки.
    """

    async def __call__(
        self,
        handler: Callable,
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        if isinstance(event, Message) and _is_allowed_message(event):
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and _is_allowed_callback(event):
            return await handler(event, data)

        event_user = data.get("event_from_user")
        user_id = getattr(event_user, "id", None)
        if user_id is None:
            return await handler(event, data)

        if await is_admin(user_id):
            return await handler(event, data)

        db_user = await get_user(user_id)
        if not db_user:
            return await handler(event, data)

        bot: Bot | None = data.get("bot")
        if bot is None:
            logger.error("SubscriptionMiddleware: bot missing in middleware data")
            return await handler(event, data)

        lang = data.get("lang", "ru")
        i18n = data.get("i18n") or (lambda key, **kwargs: get_text(key, lang, **kwargs))

        try:
            all_subscribed, unsubscribed = await check_subscription(bot, user_id)
        except Exception as exc:
            logger.error("Ошибка глобальной проверки подписки user=%d: %s", user_id, exc)
            if isinstance(event, Message):
                await event.answer(i18n("check_error"))
            else:
                await event.answer(i18n("check_error"), show_alert=True)
            return None

        if all_subscribed:
            return await handler(event, data)

        await _send_subscription_required(event, lang, i18n, unsubscribed)
        logger.info(
            "Действие user=%d заблокировано: нет подписки на %d каналов",
            user_id,
            len(unsubscribed),
        )
        return None
