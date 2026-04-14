"""
Middleware проверки активности конкурса.

Блокирует все хендлеры (кроме /profile и /winners) после END_DATE.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, Optional

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from middlewares.localization import get_text

logger = logging.getLogger(__name__)

# UTC+3 (Europe/Kiev)
_KYIV_TZ = timezone(timedelta(hours=3))

# Команды/тексты, разрешённые после окончания конкурса
_ALLOWED_AFTER_END = frozenset({
    "/profile", "/winners",
    "👤 Профиль", "👤 Профіль",
    "🏆 Победители", "🏆 Переможці",
    "🌐 Язык", "🌐 Мова",
})

# Админ-команды, всегда разрешены (даже после окончания)
_ADMIN_COMMANDS = frozenset({
    "/draw", "/admin_stats", "/casino_stats", "/refresh_menu", "/send", "/set_date", "/start",
})


async def _get_end_date() -> Optional[datetime]:
    """Получить END_DATE из базы данных."""
    from db.models import get_end_date
    return await get_end_date()


async def is_contest_active() -> bool:
    """Проверить, активен ли конкурс (текущее время < END_DATE)."""
    end_date = await _get_end_date()
    if end_date is None:
        return False  # Если дата не задана, конкурс не активен
        
    now = datetime.now(_KYIV_TZ).replace(tzinfo=None)
    return now < end_date


def _is_admin(user_id: int) -> bool:
    """Проверить, является ли пользователь администратором."""
    from config import ADMIN_IDS
    return user_id in ADMIN_IDS


class ContestActiveMiddleware(BaseMiddleware):
    """
    Middleware: блокирует действия после окончания конкурса.

    Разрешённые после END_DATE: профиль, победители, смена языка, админ-команды.
    """

    async def __call__(
        self,
        handler: Callable,
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Проверяем только Message-события
        if not isinstance(event, Message):
            return await handler(event, data)

        # Если конкурс активен — пропускаем
        if await is_contest_active():
            return await handler(event, data)

        # Конкурс завершён — проверяем, разрешена ли команда
        text = (event.text or "").strip()

        # Проверка по точному совпадению (кнопки меню)
        if text in _ALLOWED_AFTER_END:
            return await handler(event, data)

        # Проверка админ-команд (могут иметь аргументы: /extend_date 2026-12-31 23:59)
        cmd = text.split()[0] if text else ""
        cmd = cmd.split("@")[0]  # отрезаем @Username если есть
        if cmd in _ADMIN_COMMANDS and _is_admin(event.from_user.id):
            return await handler(event, data)

        # Блокируем
        lang = data.get("lang", "ru")
        await event.answer(get_text("contest_ended", lang))
        return None
