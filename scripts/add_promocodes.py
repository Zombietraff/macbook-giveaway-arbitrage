"""
Скрипт для пакетного добавления промокодов в БД.

Использование:
    uv run python scripts/add_promocodes.py

Добавляет 10 уникальных промокодов-пасхалок.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Добавляем корень проекта в sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database import close_db, init_db
from db.models import add_promocode

# 10 уникальных промокодов-пасхалок
PROMOCODES = [
    "MACBOOK2026",
    "AIRPODS_PRO",
    "LUCKY_WINNER",
    "HIDDEN_TREASURE",
    "GOLDEN_TICKET",
    "SECRET_CODE",
    "EASTER_EGG_1",
    "BONUS_LEVEL",
    "MEGA_PRIZE",
    "TOP_SECRET",
]


async def main() -> None:
    """Добавить все промокоды в БД."""
    await init_db()

    print(f"Добавление {len(PROMOCODES)} промокодов...")

    for code in PROMOCODES:
        await add_promocode(code)
        print(f"  ✅ {code}")

    await close_db()
    print(f"\nГотово! Добавлено {len(PROMOCODES)} промокодов.")


if __name__ == "__main__":
    asyncio.run(main())
