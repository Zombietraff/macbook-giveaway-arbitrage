"""
Обработчик команды /start — регистрация, анти-бот фильтры, deep link.

Логика:
1. Извлечение deep link параметра (ref_{link}).
2. Проверка: уже зарегистрирован → показать главное меню.
3. Проверка language_code против чёрного списка.
4. Проверка user.id <= MAX_USER_ID.
5. Генерация ref_link, запись пользователя в БД.
6. Если есть реферер — запись ref_by и создание referral.
7. Отправка приветственных сообщений + кнопки каналов + «Проверить подписку».
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any, Callable, Optional

from aiogram import Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message

from config import BOT_USERNAME
from db.models import (
    create_referral,
    create_user,
    get_all_channels,
    get_user,
    get_user_by_ref_link,
)
from keyboards.channels import get_channels_keyboard
from keyboards.main_menu import get_active_main_menu_keyboard, get_check_subscription_keyboard
from middlewares.localization import detect_language, get_text
from utils.checks import is_valid_language, is_valid_user_id

logger = logging.getLogger(__name__)
router = Router(name="start")


def _generate_ref_link() -> str:
    """Генерация уникальной реферальной ссылки (base64 от 6 случайных байт)."""
    return base64.urlsafe_b64encode(os.urandom(6)).decode("ascii").rstrip("=")


def _extract_ref_link(deep_link: Optional[str]) -> Optional[str]:
    """
    Извлечь реферальный код из deep link параметра.

    Args:
        deep_link: значение аргумента /start (например, 'ref_abc123').

    Returns:
        Реферальный код (например, 'abc123') или None.
    """
    if deep_link and deep_link.startswith("ref_"):
        return deep_link[4:]  # убираем 'ref_'
    return None


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    command: CommandObject,
    i18n: Callable,
    lang: str,
    **kwargs: Any,
) -> None:
    """Обработка команды /start с регистрацией и фильтрами."""
    user = message.from_user
    user_id = user.id

    logger.info(
        "Пользователь %d (%s) вызвал /start [lang=%s, tg_lang=%s, deep_link=%s]",
        user_id, user.username, lang, user.language_code, command.args,
    )

    # ──────────────────── Проверка: уже зарегистрирован? ────────────────────
    existing_user = await get_user(user_id)
    if existing_user:
        tickets = existing_user["tickets"]
        if tickets > 0:
            # Уже участвует → показать главное меню
            await message.answer(
                i18n(
                    "start_already_registered",
                    first_name=user.first_name or "User",
                    tickets=int(tickets),
                ),
                reply_markup=await get_active_main_menu_keyboard(lang),
            )
        else:
            # Зарегистрирован, но ещё не прошёл проверку подписки
            channels = await get_all_channels()
            if channels:
                await message.answer(
                    i18n("start"),
                    reply_markup=get_channels_keyboard(channels, lang),
                )
            else:
                await message.answer(
                    i18n("start"),
                    reply_markup=get_check_subscription_keyboard(lang),
                )
        return

    # ──────────────────── Анти-бот фильтр: язык ────────────────────
    if not is_valid_language(user.language_code):
        logger.warning(
            "Блокировка по языку: user=%d, lang=%s",
            user_id, user.language_code,
        )
        await message.answer(i18n("blocked_language"))
        return

    # ──────────────────── Анти-бот фильтр: ID ────────────────────
    if not is_valid_user_id(user_id):
        logger.warning("Блокировка по user_id: user=%d", user_id)
        await message.answer(i18n("blocked_user_id"))
        return

    # ──────────────────── Обработка deep link (реферал) ────────────────────
    ref_code = _extract_ref_link(command.args)
    referrer_id: Optional[int] = None

    if ref_code:
        referrer = await get_user_by_ref_link(ref_code)
        if referrer:
            referrer_id_candidate = referrer["id"]
            # Защита от самореферала
            if referrer_id_candidate != user_id:
                referrer_id = referrer_id_candidate
                logger.info(
                    "Реферал: user=%d приглашён user=%d (ref_link=%s)",
                    user_id, referrer_id, ref_code,
                )
            else:
                logger.warning("Попытка самореферала: user=%d", user_id)
                await message.answer(i18n("referral_self"))
        else:
            logger.warning(
                "Невалидный реферальный код: '%s' (user=%d)", ref_code, user_id,
            )

    # ──────────────────── Определение языка ────────────────────
    user_lang = detect_language(user.language_code)

    # ──────────────────── Генерация ref_link и регистрация ────────────────────
    ref_link = _generate_ref_link()

    await create_user(
        user_id=user_id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        language_code=user_lang,
        is_premium=bool(user.is_premium),
        ref_link=ref_link,
        ref_by=referrer_id,
    )

    logger.info(
        "Пользователь зарегистрирован: id=%d, lang=%s, premium=%s, ref_by=%s",
        user_id, user_lang, user.is_premium, referrer_id,
    )

    # ──────────────────── Создание записи реферала ────────────────────
    if referrer_id:
        await create_referral(referrer_id=referrer_id, referred_id=user_id)
        logger.info("Реферал создан: %d → %d (pending)", referrer_id, user_id)

    # ──────────────────── Используем определённый язык ────────────────────
    _i18n = lambda key, **kw: get_text(key, user_lang, **kw)

    # ──────────────────── Сообщение 1: описание конкурса ────────────────────
    await message.answer(_i18n("start"))

    # ──────────────────── Сообщение 2: каналы + кнопка проверки ────────────────────
    channels = await get_all_channels()
    if channels:
        await message.answer(
            _i18n("contest_description"),
            reply_markup=get_channels_keyboard(channels, user_lang),
        )
    else:
        # Нет каналов — только кнопка «Проверить» (Inline)
        await message.answer(
            _i18n("contest_description"),
            reply_markup=get_check_subscription_keyboard(user_lang),
        )
