"""
Конфигурация бота Contest Giveaway.

Загрузка всех параметров из переменных окружения (.env файл).
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Final

from dotenv import load_dotenv

# ──────────────────── Пути ────────────────────
BASE_DIR: Final[Path] = Path(__file__).resolve().parent
DB_PATH: Final[Path] = BASE_DIR / "contest.db"
LOCALES_DIR: Final[Path] = BASE_DIR / "locales"
LOGS_DIR: Final[Path] = BASE_DIR / "logs"

# Создать директорию для логов, если отсутствует
LOGS_DIR.mkdir(exist_ok=True)

# ──────────────────── Загрузка .env ────────────────────
load_dotenv(BASE_DIR / ".env")


def _require_env(key: str) -> str:
    """Получить переменную окружения или выбросить ошибку."""
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"Переменная окружения '{key}' обязательна. Проверьте .env файл.")
    return value


# ──────────────────── Telegram ────────────────────
BOT_TOKEN: Final[str] = _require_env("BOT_TOKEN")
BOT_USERNAME: Final[str] = os.getenv("BOT_USERNAME", "ContestBot")

# ──────────────────── Администраторы ────────────────────
ADMIN_IDS: Final[list[int]] = [
    int(uid.strip())
    for uid in _require_env("ADMIN_IDS").split(",")
    if uid.strip()
]

BLACKLIST_LANG: Final[frozenset[str]] = frozenset({
    "ar", "fa", "hi", "ur", "bn", "th", "vi", "zh", "ja", "ko",
})

# ──────────────────── Часовой пояс ────────────────────
TIMEZONE: Final[str] = "Europe/Kiev"

# ──────────────────── Казино ────────────────────
CASINO_MAX_BET: Final[int] = 5
CASINO_MIN_BALANCE: Final[int] = 2
CASINO_DAILY_LIMIT: Final[int] = 5
