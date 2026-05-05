"""
Скрипт розыгрыша — выбор победителей взвешенным рандомом.

Логика:
1. Выбрать кандидатов (tickets > 0, blocked_bot=False) и live-проверить подписку.
2. Взвешенный рандом: random.choices с весами = tickets * hidden draw_multiplier.
3. Уникальные победители получают призы из настроенного списка contest_prizes.
4. Попытка отправки сообщения; при ошибке → исключить и пересчитать.
5. Запись в таблицу winners + лог.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime

from aiogram import Bot

from config import LOGS_DIR
from db.database import get_db
from db.models import add_winner, get_draw_prize_list
from utils.checks import check_subscription
from utils.notifications import notify_winner

logger = logging.getLogger(__name__)

DRAW_LOG = LOGS_DIR / "draw.log"


class DrawPrizesNotConfiguredError(RuntimeError):
    """Призы конкурса не настроены, draw запускать нельзя."""


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

    Критерии: tickets > 0, blocked_bot = False, подписан на текущие channels.
    """
    db = await get_db()
    async with db.execute(
        """
        SELECT
            u.id,
            u.username,
            u.first_name,
            u.tickets,
            u.language_code,
            COALESCE(uts.common_chat_count, 0) AS common_chat_count,
            COALESCE(uts.draw_multiplier, 1.0) AS draw_multiplier,
            COALESCE(uts.status, 'missing') AS trust_status
        FROM users u
        LEFT JOIN user_trust_scores uts ON uts.user_id = u.id
        WHERE u.tickets > 0 AND u.blocked_bot = FALSE
        """
    ) as cursor:
        rows = await cursor.fetchall()

    _log_draw(f"Кандидатов с tickets и без blocked_bot: {len(rows)}")

    users = []
    unsubscribed_count = 0
    for row in rows:
        try:
            subscribed, unsubscribed = await check_subscription(bot, int(row["id"]))
        except Exception as exc:
            subscribed = False
            unsubscribed = []
            _log_draw(f"Ошибка live subscription check user={row['id']}: {exc}")

        if not subscribed:
            unsubscribed_count += 1
            channel_ids = [str(ch.get("channel_id")) for ch in unsubscribed]
            _log_draw(
                f"Исключён user={row['id']}: нет подписки на текущие channels {channel_ids}"
            )
            continue

        tickets = float(row["tickets"] or 0.0)
        draw_multiplier = float(row["draw_multiplier"] or 1.0)
        effective_weight = tickets * draw_multiplier
        users.append({
            "id": row["id"],
            "username": row["username"],
            "first_name": row["first_name"],
            "tickets": tickets,
            "language_code": row["language_code"],
            "common_chat_count": int(row["common_chat_count"] or 0),
            "draw_multiplier": draw_multiplier,
            "trust_status": row["trust_status"],
            "effective_weight": effective_weight,
        })

    _log_draw(
        f"Live subscription eligibility: passed={len(users)}, excluded={unsubscribed_count}"
    )
    return users


async def perform_draw(bot: Bot) -> list[dict]:
    """
    Выполнить розыгрыш и выдать настроенный список призов.

    Returns:
        Список победителей с призами.
    """
    seed = random.randint(0, 2**32 - 1)
    random.seed(seed)
    _log_draw(f"Начало розыгрыша. Seed: {seed}")

    prize_list = await get_draw_prize_list()
    prize_count = len(prize_list)
    if prize_count == 0:
        _log_draw("ОШИБКА: Призы конкурса не настроены")
        raise DrawPrizesNotConfiguredError("Призы конкурса не настроены")
    _log_draw(f"Настроенных призов: {prize_count}")

    # 1. Получить участников
    eligible = await _get_eligible_users(bot)
    _log_draw(f"Подходящих участников: {len(eligible)}")

    if len(eligible) < prize_count:
        _log_draw(f"ОШИБКА: Недостаточно участников ({len(eligible)} < {prize_count})")
        return []

    # Лог весов
    for u in eligible:
        _log_draw(
            f"  user={u['id']} tickets={u['tickets']} "
            f"multiplier={u['draw_multiplier']} effective_weight={u['effective_weight']}"
        )

    # 2. Выбор победителей
    winners: list[dict] = []
    remaining = list(eligible)
    draw_date = datetime.now()

    for prize_idx, prize in enumerate(prize_list):
        if not remaining:
            _log_draw("ОШИБКА: Не осталось кандидатов")
            break

        # Взвешенный рандом
        weights = [u["effective_weight"] for u in remaining]

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
                weights = [u["effective_weight"] for u in remaining]

    _log_draw(f"Розыгрыш завершён. Победителей: {len(winners)}")

    return winners
