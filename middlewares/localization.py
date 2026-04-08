"""
Middleware локализации.

Загружает язык пользователя из БД (или определяет по Telegram language_code
для новых пользователей) и добавляет функцию i18n в data хендлера.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from config import LOCALES_DIR
from db.models import get_user

logger = logging.getLogger(__name__)

# Поддерживаемые языки
SUPPORTED_LANGUAGES: frozenset[str] = frozenset({"ru", "uk"})
DEFAULT_LANGUAGE: str = "ru"

# ──────────────────── Кэш локалей ────────────────────
_locales_cache: Dict[str, Dict[str, str]] = {}


def _load_locales() -> None:
    """Загрузить все файлы локалей в кэш при старте."""
    global _locales_cache
    for lang in SUPPORTED_LANGUAGES:
        locale_path = LOCALES_DIR / f"{lang}.json"
        if locale_path.exists():
            with open(locale_path, "r", encoding="utf-8") as f:
                _locales_cache[lang] = json.load(f)
            logger.info("Загружены локали: %s (%d ключей)", lang, len(_locales_cache[lang]))
        else:
            logger.warning("Файл локали не найден: %s", locale_path)
            _locales_cache[lang] = {}


# Загружаем при импорте модуля
_load_locales()


def get_plural(amount: float | int, lang: str = "ru") -> str:
    """Возвращает правильную форму слова 'билет' в зависимости от количества и языка."""
    if lang == "uk":
        word_forms = ("квиток", "квитка", "квитків")
    else:
        word_forms = ("билет", "билета", "билетов")

    if isinstance(amount, float) and not amount.is_integer():
        return word_forms[1]
    
    amount_int = int(amount)
    n = abs(amount_int) % 100
    n1 = n % 10

    if n > 10 and n < 20: 
        return word_forms[2]
    if n1 > 1 and n1 < 5: 
        return word_forms[1]
    if n1 == 1: 
        return word_forms[0]
    return word_forms[2]


def get_text(key: str, lang: str = DEFAULT_LANGUAGE, **kwargs: Any) -> str:
    """
    Получить локализованный текст по ключу.

    Args:
        key: ключ текста в JSON-файле локали.
        lang: код языка ('ru' или 'uk').
        **kwargs: именованные параметры для подстановки в текст.

    Returns:
        Локализованный текст с подставленными параметрами.
        Если ключ не найден — возвращает ключ с префиксом '⚠️'.
    """
    if lang not in _locales_cache:
        lang = DEFAULT_LANGUAGE

    locale_data = _locales_cache.get(lang, {})
    text = locale_data.get(key)

    if text is None:
        # Фоллбэк на русский
        text = _locales_cache.get(DEFAULT_LANGUAGE, {}).get(key)

    if text is None:
        logger.warning("Ключ локализации не найден: '%s' (lang=%s)", key, lang)
        return f"⚠️ [{key}]"

    if kwargs:
        if "tickets" in kwargs and "tickets_word" not in kwargs:
            kwargs["tickets_word"] = get_plural(kwargs["tickets"], lang)
        if "total" in kwargs and "total_word" not in kwargs:
            kwargs["total_word"] = get_plural(kwargs["total"], lang)
            
        try:
            text = text.format(**kwargs)
        except KeyError as e:
            logger.error("Ошибка подстановки в локали '%s': %s", key, e)

    return text


def detect_language(telegram_lang: Optional[str]) -> str:
    """
    Определить язык пользователя по Telegram language_code.

    Украинский (uk) оставляем украинским, всё остальное → русский.
    """
    if telegram_lang and telegram_lang.lower().startswith("uk"):
        return "uk"
    return DEFAULT_LANGUAGE


class LocalizationMiddleware(BaseMiddleware):
    """
    Middleware, добавляющий i18n-функцию и язык пользователя в data хендлера.

    В хендлерах доступно через:
        - data["i18n"](key, **kwargs) → локализованный текст
        - data["lang"] → код языка ('ru' / 'uk')
    """

    async def __call__(
        self,
        handler: Callable,
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Определяем user_id из события
        user_id: Optional[int] = None
        lang: str = DEFAULT_LANGUAGE

        # Извлекаем пользователя из разных типов событий
        event_user = data.get("event_from_user")
        if event_user:
            user_id = event_user.id

        if user_id:
            # Пытаемся получить язык из БД
            db_user = await get_user(user_id)
            if db_user:
                lang = db_user["language_code"] or DEFAULT_LANGUAGE
            elif event_user:
                # Новый пользователь — определяем по Telegram
                lang = detect_language(
                    getattr(event_user, "language_code", None)
                )

        # Добавляем в data для хендлеров
        data["lang"] = lang
        data["i18n"] = lambda key, **kwargs: get_text(key, lang, **kwargs)

        return await handler(event, data)
