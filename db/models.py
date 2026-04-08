"""
CRUD-функции для работы с таблицами БД.

Все функции асинхронные и используют aiosqlite.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Optional

import aiosqlite

from db.database import get_db

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════
#  USERS
# ════════════════════════════════════════════════════════════

async def get_user(user_id: int) -> Optional[aiosqlite.Row]:
    """Получить пользователя по Telegram ID."""
    db = await get_db()
    async with db.execute(
        "SELECT * FROM users WHERE id = ?", (user_id,)
    ) as cursor:
        return await cursor.fetchone()


async def create_user(
    user_id: int,
    username: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str],
    language_code: str,
    is_premium: bool,
    ref_link: str,
    ref_by: Optional[int] = None,
) -> None:
    """Создать нового пользователя."""
    db = await get_db()
    await db.execute(
        """
        INSERT OR IGNORE INTO users
            (id, username, first_name, last_name, language_code, is_premium, ref_link, ref_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, username, first_name, last_name, language_code, is_premium, ref_link, ref_by),
    )
    await db.commit()
    logger.info("Пользователь %d зарегистрирован.", user_id)


async def update_user_tickets(user_id: int, tickets: float) -> None:
    """Установить количество билетов пользователю."""
    db = await get_db()
    await db.execute(
        "UPDATE users SET tickets = ? WHERE id = ?",
        (tickets, user_id),
    )
    await db.commit()


async def add_user_tickets(user_id: int, amount: float) -> None:
    """Добавить билеты пользователю (инкремент)."""
    db = await get_db()
    await db.execute(
        "UPDATE users SET tickets = tickets + ? WHERE id = ?",
        (amount, user_id),
    )
    await db.commit()


async def update_user_language(user_id: int, language_code: str) -> None:
    """Обновить язык пользователя."""
    db = await get_db()
    await db.execute(
        "UPDATE users SET language_code = ? WHERE id = ?",
        (language_code, user_id),
    )
    await db.commit()


async def update_last_check(user_id: int) -> None:
    """Обновить дату последней проверки подписки."""
    db = await get_db()
    await db.execute(
        "UPDATE users SET last_check_at = ? WHERE id = ?",
        (datetime.now(UTC).isoformat(), user_id),
    )
    await db.commit()


async def set_user_blocked(user_id: int, blocked: bool = True) -> None:
    """Установить флаг блокировки бота пользователем."""
    db = await get_db()
    await db.execute(
        "UPDATE users SET blocked_bot = ? WHERE id = ?",
        (blocked, user_id),
    )
    await db.commit()


async def get_user_by_ref_link(ref_link: str) -> Optional[aiosqlite.Row]:
    """Найти пользователя по реферальной ссылке."""
    db = await get_db()
    async with db.execute(
        "SELECT * FROM users WHERE ref_link = ?", (ref_link,)
    ) as cursor:
        return await cursor.fetchone()


# ════════════════════════════════════════════════════════════
#  CHANNELS
# ════════════════════════════════════════════════════════════

async def get_all_channels() -> list[aiosqlite.Row]:
    """Получить все каналы для проверки подписки."""
    db = await get_db()
    async with db.execute("SELECT * FROM channels") as cursor:
        return await cursor.fetchall()


async def add_channel(channel_id: str, title: str, invite_link: str) -> None:
    """Добавить канал для обязательной подписки."""
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO channels (channel_id, title, invite_link) VALUES (?, ?, ?)",
        (channel_id, title, invite_link),
    )
    await db.commit()


# ════════════════════════════════════════════════════════════
#  PROMOCODES
# ════════════════════════════════════════════════════════════

async def get_promocode(code: str) -> Optional[aiosqlite.Row]:
    """Получить промокод по коду."""
    db = await get_db()
    async with db.execute(
        "SELECT * FROM promocodes WHERE code = ?", (code,)
    ) as cursor:
        return await cursor.fetchone()


async def activate_promocode(code: str, user_id: int) -> None:
    """Активировать промокод: установить used_by и activated_at."""
    db = await get_db()
    await db.execute(
        "UPDATE promocodes SET used_by = ?, activated_at = ? WHERE code = ?",
        (user_id, datetime.now(UTC).isoformat(), code),
    )
    await db.commit()


async def add_promocode(code: str, channel_id: Optional[int] = None) -> None:
    """Добавить промокод в БД."""
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO promocodes (code, channel_id) VALUES (?, ?)",
        (code, channel_id),
    )
    await db.commit()


# ════════════════════════════════════════════════════════════
#  REFERRALS
# ════════════════════════════════════════════════════════════

async def create_referral(referrer_id: int, referred_id: int) -> None:
    """Создать запись о реферале со статусом 'pending'."""
    db = await get_db()
    await db.execute(
        "INSERT INTO referrals (referrer_id, referred_id, status) VALUES (?, ?, 'pending')",
        (referrer_id, referred_id),
    )
    await db.commit()


async def update_referral_status(
    referrer_id: int, referred_id: int, status: str
) -> None:
    """Обновить статус реферала."""
    db = await get_db()
    await db.execute(
        "UPDATE referrals SET status = ? WHERE referrer_id = ? AND referred_id = ?",
        (status, referrer_id, referred_id),
    )
    await db.commit()


async def get_pending_referral(referred_id: int) -> Optional[aiosqlite.Row]:
    """Получить ожидающий реферал для пользователя."""
    db = await get_db()
    async with db.execute(
        "SELECT * FROM referrals WHERE referred_id = ? AND status = 'pending'",
        (referred_id,),
    ) as cursor:
        return await cursor.fetchone()


async def count_completed_referrals(referrer_id: int) -> int:
    """Подсчитать количество завершённых рефералов для пользователя."""
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND status = 'completed'",
        (referrer_id,),
    ) as cursor:
        row = await cursor.fetchone()
        return row[0] if row else 0


# ════════════════════════════════════════════════════════════
#  WINNERS
# ════════════════════════════════════════════════════════════

async def add_winner(user_id: int, prize: str, draw_date: datetime) -> None:
    """Записать победителя розыгрыша."""
    db = await get_db()
    await db.execute(
        "INSERT INTO winners (user_id, prize, draw_date) VALUES (?, ?, ?)",
        (user_id, prize, draw_date.isoformat()),
    )
    await db.commit()


async def get_all_winners() -> list[aiosqlite.Row]:
    """Получить всех победителей."""
    db = await get_db()
    async with db.execute(
        """
        SELECT w.*, u.username, u.first_name
        FROM winners w
        JOIN users u ON w.user_id = u.id
        ORDER BY w.id
        """
    ) as cursor:
        return await cursor.fetchall()


async def clear_winners() -> None:
    """Очистить таблицу победителей (например, при перезапуске конкурса)."""
    db = await get_db()
    await db.execute("DELETE FROM winners")
    await db.commit()


# ════════════════════════════════════════════════════════════
#  SETTINGS
# ════════════════════════════════════════════════════════════

async def get_end_date() -> Optional[datetime]:
    """Получить дату окончания розыгрыша из БД."""
    db = await get_db()
    async with db.execute(
        "SELECT value FROM settings WHERE key = 'end_date'"
    ) as cursor:
        row = await cursor.fetchone()
        if row and row[0]:
            try:
                return datetime.strptime(row[0], "%Y-%m-%d %H:%M")
            except ValueError:
                pass
    return None


async def set_end_date(new_date: datetime) -> None:
    """Установить или обновить дату окончания розыгрыша."""
    db = await get_db()
    date_str = new_date.strftime("%Y-%m-%d %H:%M")
    await db.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('end_date', ?)",
        (date_str,)
    )
    await db.commit()
