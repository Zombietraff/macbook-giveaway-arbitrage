"""
Скрипт для пакетного добавления промокодов в БД.

Использование:
    uv run python scripts/add_promocodes.py

Добавляет 10 уникальных промокодов-пасхалок.
"""

from __future__ import annotations

import asyncio
import argparse
import sys
from pathlib import Path

# Добавляем корень проекта в sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database import close_db, init_db
from db.models import add_promocode

# 10 уникальных промокодов-пасхалок
# PROMOCODES = [
#     "MACBOOK2026",
#     "AIRPODS_PRO",
#     "LUCKY_WINNER",
#     "HIDDEN_TREASURE",
#     "GOLDEN_TICKET",
#     "SECRET_CODE",
#     "EASTER_EGG_1",
#     "BONUS_LEVEL",
#     "MEGA_PRIZE",
#     "TOP_SECRET",
# ]



PROMOCODES = [
    "Владыка",
    "ДжекиЧАН",
    "+500",
    
    "ChillGuy",
    "1+1=10",
    "Лебовски2.0",
    
    "Bear",
    "СОЛОАНДРЕЙ",
    "ХАВДУЮДУ",
    
    "НАХАРАКТЕРЕ",
    "20НА80",
    "NutraFree",
    
    "БЕНЯ",
    "ТРАКТОРИСТ",
    "Rhyno",
    
    "ФЕЙСБУКОВИЧИ",
    "АНДРОМЕДА",
    "РОИ20",
    
    "НЕСЛИВАЮВТЕСТ",
    "ФИКС+ПРОЦЕНТ",
    "БЫСТРООБУЧАЮСЬ",
    
    "ЮТУБЖИВ",
    "МАНКИДЖОБ",
    "ФАНАТСВИПОВ",
    
    "НАДОКРАСТЬ",
    "NINJA007",
    "SHADOW",
    
    "ЗОМБАРЬ",
    "МЕНТАЛКА",
    "АРБИТРАН",
]



async def main() -> None:
    """Добавить все промокоды в БД."""
    parser = argparse.ArgumentParser(description="Добавить промокоды в БД")
    parser.add_argument(
        "--uses-limit",
        type=int,
        default=1,
        help="Сколько раз можно использовать каждый промокод",
    )
    args = parser.parse_args()
    if args.uses_limit < 1:
        raise SystemExit("--uses-limit должен быть >= 1")

    await init_db()

    print(f"Добавление {len(PROMOCODES)} промокодов (лимит: {args.uses_limit})...")

    for code in PROMOCODES:
        await add_promocode(code, uses_limit=args.uses_limit)
        print(f"  ✅ {code}")

    await close_db()
    print(f"\nГотово! Добавлено {len(PROMOCODES)} промокодов.")


if __name__ == "__main__":
    asyncio.run(main())
