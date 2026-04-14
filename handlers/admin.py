"""
Админ-команды для управления конкурсом.

- /admin_stats — статистика конкурса.
- /set_date YYYY-MM-DD HH:MM — установка или продление даты окончания.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

import config
from db.database import get_db
from db.models import clear_winners, get_casino_stats, get_end_date, set_end_date
from utils.timezone import get_kyiv_day_bounds_utc

logger = logging.getLogger(__name__)
router = Router(name="admin")

# Файл лога для действий админа
_ADMIN_LOG = config.LOGS_DIR / "admin.log"


def _is_admin(user_id: int) -> bool:
    """Проверить, является ли пользователь администратором."""
    return user_id in config.ADMIN_IDS


def _log_admin_action(admin_id: int, action: str) -> None:
    """Записать действие администратора в лог-файл."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] admin={admin_id} action={action}\n"
    with open(_ADMIN_LOG, "a", encoding="utf-8") as f:
        f.write(line)
    logger.info("Admin action: %s (by %d)", action, admin_id)


def _fmt_amount(value: float) -> str:
    """Форматировать число без лишних нулей после запятой."""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


@router.message(Command("admin_stats"))
async def admin_stats(message: Message, **kwargs: Any) -> None:
    """Показать статистику конкурса (только для админов)."""
    if not _is_admin(message.from_user.id):
        return

    db = await get_db()

    async with db.execute("SELECT COUNT(*) FROM users") as cur:
        total_users = (await cur.fetchone())[0]
    async with db.execute("SELECT COUNT(*) FROM users WHERE tickets > 0") as cur:
        active_users = (await cur.fetchone())[0]
    async with db.execute("SELECT SUM(tickets) FROM users") as cur:
        total_tickets = (await cur.fetchone())[0] or 0
    async with db.execute("SELECT COUNT(*) FROM referrals WHERE status='completed'") as cur:
        total_referrals = (await cur.fetchone())[0]
    async with db.execute("SELECT COUNT(*) FROM promocodes WHERE used_by IS NOT NULL") as cur:
        used_promos = (await cur.fetchone())[0]
    async with db.execute("SELECT COUNT(*) FROM users WHERE blocked_bot=TRUE") as cur:
        blocked = (await cur.fetchone())[0]

    end_date = await get_end_date()
    end_date_str = end_date.strftime('%Y-%m-%d %H:%M') if end_date else "Не установлена"

    text = (
        "📊 <b>Статистика конкурса</b>\n\n"
        f"👥 Всего пользователей: <b>{total_users}</b>\n"
        f"✅ Активных участников: <b>{active_users}</b>\n"
        f"🎫 Всего билетов: <b>{int(total_tickets)}</b>\n"
        f"👥 Рефералов (completed): <b>{total_referrals}</b>\n"
        f"🥚 Промокодов использовано: <b>{used_promos}</b>\n"
        f"🚫 Заблокировали бота: <b>{blocked}</b>\n\n"
        f"📅 Дата окончания: <b>{end_date_str}</b>"
    )

    await message.answer(text)
    _log_admin_action(message.from_user.id, "admin_stats")


@router.message(Command("set_date"))
async def set_date(message: Message, **kwargs: Any) -> None:
    """Установить или продлить дату окончания конкурса (только для админов)."""
    if not _is_admin(message.from_user.id):
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "⚠️ Формат: <code>/set_date YYYY-MM-DD HH:MM</code>",
        )
        return

    date_str = parts[1].strip()
    try:
        new_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
    except ValueError:
        await message.answer(
            "❌ Неверный формат даты. Используйте: <code>YYYY-MM-DD HH:MM</code>",
        )
        return

    old_date = await get_end_date()
    old_date_str = old_date.strftime('%Y-%m-%d %H:%M') if old_date else "Не установлена"
    
    await set_end_date(new_date)
    await clear_winners()

    await message.answer(
        f"✅ Дата окончания обновлена:\n"
        f"Было: <b>{old_date_str}</b>\n"
        f"Стало: <b>{new_date.strftime('%Y-%m-%d %H:%M')}</b>\n\n"
        f"🧹 <i>Предыдущие победители сброшены.</i>",
    )

    _log_admin_action(
        message.from_user.id,
        f"set_date: {old_date_str} → {new_date}",
    )


@router.message(Command("casino_stats"))
async def casino_stats(message: Message, **kwargs: Any) -> None:
    """Показать статистику модуля казино (только для админов)."""
    if not _is_admin(message.from_user.id):
        return

    day_start_utc, day_end_utc = get_kyiv_day_bounds_utc()
    stats = await get_casino_stats(day_start_utc, day_end_utc)

    top_players = stats["top_players"]
    if top_players:
        top_lines = [
            f"{idx}. {player['display_name']} — <b>{player['spins']}</b>"
            for idx, player in enumerate(top_players, 1)
        ]
        top_text = "\n".join(top_lines)
    else:
        top_text = "—"

    text = (
        "🎰 <b>Casino stats</b>\n\n"
        f"🗓 Спинов сегодня: <b>{stats['today_spins']}</b>\n"
        f"📦 Спинов всего: <b>{stats['total_spins']}</b>\n\n"
        f"💵 Ставок сегодня: <b>{_fmt_amount(stats['today_bets'])}</b>\n"
        f"💸 Выплат сегодня: <b>{_fmt_amount(stats['today_payouts'])}</b>\n"
        f"💰 Ставок всего: <b>{_fmt_amount(stats['total_bets'])}</b>\n"
        f"🏧 Выплат всего: <b>{_fmt_amount(stats['total_payouts'])}</b>\n"
        f"📈 House profit: <b>{_fmt_amount(stats['house_profit'])}</b>\n"
        f"🎯 Winrate: <b>{stats['win_rate']:.2f}%</b>\n\n"
        f"🔴 Loss: <b>{stats['breakdown']['loss']}</b>\n"
        f"🟢 Win: <b>{stats['breakdown']['win']}</b>\n"
        f"🎰 Jackpot: <b>{stats['breakdown']['jackpot']}</b>\n\n"
        f"🏆 Топ-3 игроков по спинам:\n{top_text}"
    )

    await message.answer(text)
    _log_admin_action(message.from_user.id, "casino_stats")


@router.message(Command("draw"))
async def trigger_draw(message: Message, bot: Bot, **kwargs: Any) -> None:
    """Запустить розыгрыш (только для админов)."""
    if not _is_admin(message.from_user.id):
        return

    from aiogram import Bot as BotType
    from utils.draw import perform_draw

    await message.answer("🎲 Запуск розыгрыша...")
    _log_admin_action(message.from_user.id, "draw_started")

    try:
        winners = await perform_draw(bot)

        if not winners:
            await message.answer("❌ Розыгрыш не удался: недостаточно участников.")
            return

        lines = ["🏆 <b>Результаты розыгрыша:</b>\n"]
        for idx, w in enumerate(winners, 1):
            name = w.get("username") or w.get("first_name") or str(w["user_id"])
            if w.get("username"):
                name = f"@{name}"
            lines.append(f"{idx}. {name} — <b>{w['prize']}</b>")

        await message.answer("\n".join(lines))
        _log_admin_action(message.from_user.id, f"draw_completed: {len(winners)} winners")

    except Exception as e:
        logger.error("Ошибка розыгрыша: %s", e)
        await message.answer(f"❌ Ошибка: {e}")
        _log_admin_action(message.from_user.id, f"draw_error: {e}")
