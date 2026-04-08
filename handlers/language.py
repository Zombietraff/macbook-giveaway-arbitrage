"""
Обработчик смены языка.

Кнопка «🌐 Язык» → показать текущий язык и выбор.
Inline-кнопки «🇷🇺 Русский» / «🇺🇦 Українська» → переключение.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from db.models import get_user, update_user_language
from keyboards.main_menu import get_language_keyboard, get_main_menu_keyboard
from middlewares.localization import get_text

logger = logging.getLogger(__name__)
router = Router(name="language")


@router.message(F.text.in_({"🌐 Язык", "🌐 Мова"}))
async def show_language_menu(message: Message, lang: str, i18n: Callable, **kwargs: Any) -> None:
    """Показать текущий язык и кнопки выбора."""
    lang_name = i18n("lang_name")
    await message.answer(
        i18n("lang_current", lang_name=lang_name),
        reply_markup=get_language_keyboard(),
    )


@router.callback_query(F.data.in_({"lang_ru", "lang_uk"}))
async def change_language(callback: CallbackQuery, lang: str, i18n: Callable, **kwargs: Any) -> None:
    """Обработка выбора языка через Inline-кнопку."""
    new_lang = callback.data.replace("lang_", "")  # "ru" или "uk"

    if new_lang == lang:
        await callback.answer()
        return

    user_id = callback.from_user.id
    await update_user_language(user_id, new_lang)

    # Новый i18n с новым языком
    confirmation = get_text("lang_changed", new_lang)

    await callback.message.edit_text(confirmation)
    await callback.answer()

    # Обновляем главное меню с новым языком
    await callback.message.answer(
        get_text("menu_back", new_lang),
        reply_markup=get_main_menu_keyboard(new_lang),
    )

    logger.info("Пользователь %d сменил язык: %s → %s", user_id, lang, new_lang)
