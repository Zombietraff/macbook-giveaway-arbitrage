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
# Для локального Pinggy-тестирования WEBAPP_URL часто меняется.
# override=True защищает от устаревшего WEBAPP_URL, экспортированного в shell.
load_dotenv(BASE_DIR / ".env", override=True)


def _require_env(key: str) -> str:
    """Получить переменную окружения или выбросить ошибку."""
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"Переменная окружения '{key}' обязательна. Проверьте .env файл.")
    return value


def _parse_int_list(raw_value: str) -> list[int]:
    """Распарсить comma-separated список Telegram ID."""
    return [
        int(uid.strip())
        for uid in raw_value.split(",")
        if uid.strip()
    ]


# ──────────────────── Telegram ────────────────────
BOT_TOKEN: Final[str] = _require_env("BOT_TOKEN")
BOT_USERNAME: Final[str] = os.getenv("BOT_USERNAME", "ContestBot")
WEBAPP_URL: Final[str] = os.getenv("WEBAPP_URL", "https://your-domain.com")
MAX_USER_ID: Final[int] = int(os.getenv("MAX_USER_ID", "8000000000"))

# ──────────────────── Администраторы ────────────────────
_owner_ids_raw = os.getenv("OWNER_IDS") or os.getenv("ADMIN_IDS")
if not _owner_ids_raw:
    raise RuntimeError("Переменная окружения 'OWNER_IDS' обязательна. Проверьте .env файл.")

OWNER_IDS: Final[list[int]] = _parse_int_list(_owner_ids_raw)

# Deprecated compatibility alias. Runtime-права проверяются через OWNER_IDS
# и temporary_admins в БД, а не через ADMIN_IDS.
ADMIN_IDS: Final[list[int]] = OWNER_IDS

BLACKLIST_LANG: Final[frozenset[str]] = frozenset({
    "ar", "fa", "hi", "ur", "bn", "th", "vi", "zh", "ja", "ko",
})

# ──────────────────── Часовой пояс ────────────────────
# По умолчанию используем канонический IANA-ключ Europe/Kyiv.
# Можно переопределить через переменную окружения TIMEZONE.
TIMEZONE: Final[str] = os.getenv("TIMEZONE", "Europe/Kyiv")

# ──────────────────── Казино ────────────────────
CASINO_MAX_BET: Final[int] = 5
CASINO_MIN_BALANCE: Final[int] = 2
CASINO_DAILY_LIMIT: Final[int] = 5
