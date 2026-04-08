"""
Скрипт розыгрыша — выбор победителей взвешенным рандомом.

Логика:
1. Выбрать активных участников (tickets > 0, blocked_bot=False).
2. Взвешенный рандом: random.choices с весами = tickets.
3. 4 уникальных победителя: первые 3 → MacBook Neo, 4-й → AirPods 3 Pro.
4. Попытка отправки сообщения; при ошибке → исключить и пересчитать.
5. Запись в таблицу winners + лог.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime
from pathlib import Path
from typing import Optional

from aiogram import Bot

from config import LOGS_DIR
from db.database import get_db
from db.models import add_winner, get_user
from utils.notifications import notify_winner

logger = logging.getLogger(__name__)

DRAW_LOG = LOGS_DIR / "draw.log"

PRIZES = ["MacBook Neo", "MacBook Neo", "MacBook Neo", "AirPods 3 Pro"]


def _log_draw(message: str) -> None:
    """Записать в лог файл розыгрыша."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}\n"
    with open(DRAW_LOG, "a", encoding="utf-8") as f:
        f.write(line)
    logger.info("DRAW: %s", message)


async def _get_eligible_users(bot: Bot) -> list[dict]:
    """
    Получить список подходящих участников.

    Критерии: tickets > 0, blocked_bot = False.
    """
    db = await get_db()
    async with db.execute(
        """
        SELECT id, username, first_name, tickets, language_code
        FROM users
        WHERE tickets > 0 AND blocked_bot = FALSE
        """
    ) as cursor:
        rows = await cursor.fetchall()

    users = []
    for row in rows:
        users.append({
            "id": row["id"],
            "username": row["username"],
            "first_name": row["first_name"],
            "tickets": row["tickets"],
            "language_code": row["language_code"],
        })

    return users


async def perform_draw(bot: Bot) -> list[dict]:
    """
    Выполнить розыгрыш: выбрать 4 уникальных победителей.

    Returns:
        Список победителей с призами.
    """
    seed = random.randint(0, 2**32 - 1)
    random.seed(seed)
    _log_draw(f"Начало розыгрыша. Seed: {seed}")

    # 1. Получить участников
    eligible = await _get_eligible_users(bot)
    _log_draw(f"Подходящих участников: {len(eligible)}")

    if len(eligible) < 4:
        _log_draw(f"ОШИБКА: Недостаточно участников ({len(eligible)} < 4)")
        return []

    # Лог весов
    for u in eligible:
        _log_draw(f"  user={u['id']} tickets={u['tickets']}")

    # 2. Выбор победителей
    winners: list[dict] = []
    remaining = list(eligible)
    draw_date = datetime.now()

    for prize_idx, prize in enumerate(PRIZES):
        if not remaining:
            _log_draw("ОШИБКА: Не осталось кандидатов")
            break

        # Взвешенный рандом
        weights = [u["tickets"] for u in remaining]

        while remaining:
            selected = random.choices(remaining, weights=weights, k=1)[0]

            # Попытка уведомить победителя
            lang = selected.get("language_code", "ru")
            delivered = await notify_winner(
                bot=bot,
                user_id=selected["id"],
                prize=prize,
                lang=lang,
            )

            if delivered:
                # Успех — записываем победителя
                winner_entry = {
                    "user_id": selected["id"],
                    "username": selected["username"],
                    "first_name": selected["first_name"],
                    "prize": prize,
                }
                winners.append(winner_entry)

                await add_winner(selected["id"], prize, draw_date)
                _log_draw(
                    f"ПОБЕДИТЕЛЬ #{prize_idx + 1}: user={selected['id']} "
                    f"(@{selected['username']}) → {prize}"
                )

                # Удаляем из пула
                remaining = [u for u in remaining if u["id"] != selected["id"]]
                break
            else:
                # Не удалось доставить — исключаем и повторяем
                _log_draw(
                    f"Не удалось уведомить user={selected['id']}. Исключение и пересчёт."
                )
                remaining = [u for u in remaining if u["id"] != selected["id"]]
                weights = [u["tickets"] for u in remaining]

    _log_draw(f"Розыгрыш завершён. Победителей: {len(winners)}")

    return winners
