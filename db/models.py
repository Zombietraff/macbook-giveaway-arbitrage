"""
CRUD-функции для работы с таблицами БД.

Все функции асинхронные и используют aiosqlite.
"""

from __future__ import annotations

import logging
import json
from datetime import UTC, datetime
from typing import Any, Optional

import aiosqlite

from db.database import get_db
from utils.timezone import to_sqlite_utc

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


async def remove_channel(channel_id: str) -> None:
    """Удалить канал обязательной подписки."""
    db = await get_db()
    await db.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
    await db.commit()


async def update_channel(channel_id: str, title: str, invite_link: str) -> None:
    """Обновить данные канала (название и ссылку)."""
    db = await get_db()
    await db.execute(
        "UPDATE channels SET title = ?, invite_link = ? WHERE channel_id = ?",
        (title, invite_link, channel_id),
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


async def get_all_promocodes(limit: int = 50) -> list[aiosqlite.Row]:
    """Получить последние промокоды для админского просмотра."""
    db = await get_db()
    async with db.execute(
        """
        SELECT *
        FROM promocodes
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ) as cursor:
        return await cursor.fetchall()


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


async def get_setting(key: str) -> Optional[str]:
    """Получить значение настройки по ключу."""
    db = await get_db()
    async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
        row = await cursor.fetchone()
        return str(row["value"]) if row and row["value"] is not None else None


async def set_setting(key: str, value: str) -> None:
    """Установить или обновить настройку."""
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, value),
    )
    await db.commit()


# ════════════════════════════════════════════════════════════
#  ADMINS / AUDIT
# ════════════════════════════════════════════════════════════

async def add_temporary_admin(
    user_id: int,
    added_by: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
) -> None:
    """Добавить или восстановить временного админа."""
    db = await get_db()
    await db.execute(
        """
        INSERT INTO temporary_admins (user_id, username, first_name, added_by, revoked_at)
        VALUES (?, ?, ?, ?, NULL)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name,
            added_by = excluded.added_by,
            revoked_at = NULL
        """,
        (user_id, username, first_name, added_by),
    )
    await db.commit()


async def revoke_temporary_admin(user_id: int) -> None:
    """Снять временного админа."""
    db = await get_db()
    await db.execute(
        "UPDATE temporary_admins SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
        (datetime.now(UTC).isoformat(), user_id),
    )
    await db.commit()


async def is_active_temporary_admin(user_id: int) -> bool:
    """Проверить, активен ли временный админ."""
    db = await get_db()
    async with db.execute(
        """
        SELECT 1
        FROM temporary_admins
        WHERE user_id = ? AND revoked_at IS NULL
        LIMIT 1
        """,
        (user_id,),
    ) as cursor:
        return (await cursor.fetchone()) is not None


async def get_temporary_admins(include_revoked: bool = False) -> list[aiosqlite.Row]:
    """Получить список временных админов."""
    db = await get_db()
    where = "" if include_revoked else "WHERE revoked_at IS NULL"
    async with db.execute(
        f"""
        SELECT *
        FROM temporary_admins
        {where}
        ORDER BY created_at DESC
        """
    ) as cursor:
        return await cursor.fetchall()


async def add_admin_audit_log(
    actor_id: int,
    action: str,
    target_id: Optional[int] = None,
    payload: Optional[dict[str, Any] | str] = None,
) -> None:
    """Записать действие админа в аудит."""
    db = await get_db()
    if isinstance(payload, dict):
        payload_value = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    else:
        payload_value = payload

    await db.execute(
        """
        INSERT INTO admin_audit_log (actor_id, action, target_id, payload)
        VALUES (?, ?, ?, ?)
        """,
        (actor_id, action, target_id, payload_value),
    )
    await db.commit()


# ════════════════════════════════════════════════════════════
#  CONTEST RESET / ARCHIVE
# ════════════════════════════════════════════════════════════

async def _collect_contest_reset_preview(db: aiosqlite.Connection) -> dict[str, int | float]:
    """Собрать счётчики данных, которые будут сброшены."""
    async with db.execute("SELECT COUNT(*) FROM users WHERE tickets != 0") as cursor:
        users_with_tickets_count = int((await cursor.fetchone())[0] or 0)
    async with db.execute("SELECT COALESCE(SUM(tickets), 0) FROM users WHERE tickets != 0") as cursor:
        total_tickets = float((await cursor.fetchone())[0] or 0.0)
    async with db.execute("SELECT COUNT(*) FROM winners") as cursor:
        winners_count = int((await cursor.fetchone())[0] or 0)
    async with db.execute("SELECT COUNT(*) FROM casino_spins") as cursor:
        casino_spins_count = int((await cursor.fetchone())[0] or 0)
    async with db.execute("SELECT COUNT(*) FROM channels") as cursor:
        channels_count = int((await cursor.fetchone())[0] or 0)
    async with db.execute("SELECT COUNT(*) FROM promocodes") as cursor:
        promocodes_count = int((await cursor.fetchone())[0] or 0)
    async with db.execute("SELECT COUNT(*) FROM temporary_admins WHERE revoked_at IS NULL") as cursor:
        active_temp_admins_count = int((await cursor.fetchone())[0] or 0)
    async with db.execute("SELECT COUNT(*) FROM temporary_admins") as cursor:
        temp_admins_count = int((await cursor.fetchone())[0] or 0)

    return {
        "users_with_tickets_count": users_with_tickets_count,
        "total_tickets": total_tickets,
        "winners_count": winners_count,
        "casino_spins_count": casino_spins_count,
        "channels_count": channels_count,
        "promocodes_count": promocodes_count,
        "active_temp_admins_count": active_temp_admins_count,
        "temp_admins_count": temp_admins_count,
    }


async def get_contest_reset_preview() -> dict[str, int | float]:
    """Получить preview-счётчики owner reset без изменения БД."""
    db = await get_db()
    return await _collect_contest_reset_preview(db)


async def reset_contest_with_archive(actor_id: int) -> dict[str, int | float]:
    """
    Архивировать состояние конкурса и выполнить reset в одной транзакции.

    Не удаляет users/settings/referrals/user_flags/admin_audit_log.
    """
    db = await get_db()
    await db.execute("BEGIN IMMEDIATE")

    try:
        preview = await _collect_contest_reset_preview(db)

        cursor = await db.execute(
            """
            INSERT INTO contest_reset_runs (
                actor_id,
                users_with_tickets_count,
                total_tickets,
                winners_count,
                casino_spins_count,
                channels_count,
                promocodes_count,
                active_temp_admins_count,
                temp_admins_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                actor_id,
                preview["users_with_tickets_count"],
                preview["total_tickets"],
                preview["winners_count"],
                preview["casino_spins_count"],
                preview["channels_count"],
                preview["promocodes_count"],
                preview["active_temp_admins_count"],
                preview["temp_admins_count"],
            ),
        )
        reset_id = int(cursor.lastrowid)

        await db.execute(
            """
            INSERT INTO contest_reset_user_tickets (
                reset_id,
                user_id,
                username,
                first_name,
                last_name,
                language_code,
                is_premium,
                ref_link,
                ref_by,
                tickets,
                registered_at,
                last_check_at,
                blocked_bot
            )
            SELECT
                ?,
                id,
                username,
                first_name,
                last_name,
                language_code,
                is_premium,
                ref_link,
                ref_by,
                tickets,
                registered_at,
                last_check_at,
                blocked_bot
            FROM users
            WHERE tickets != 0
            """,
            (reset_id,),
        )
        await db.execute(
            """
            INSERT INTO contest_reset_winners (reset_id, original_id, user_id, prize, draw_date)
            SELECT ?, id, user_id, prize, draw_date
            FROM winners
            """,
            (reset_id,),
        )
        await db.execute(
            """
            INSERT INTO contest_reset_casino_spins (
                reset_id,
                original_id,
                user_id,
                bet_amount,
                dice_value,
                result_type,
                multiplier,
                balance_before,
                balance_after,
                created_at
            )
            SELECT
                ?,
                id,
                user_id,
                bet_amount,
                dice_value,
                result_type,
                multiplier,
                balance_before,
                balance_after,
                created_at
            FROM casino_spins
            """,
            (reset_id,),
        )
        await db.execute(
            """
            INSERT INTO contest_reset_channels (reset_id, original_id, channel_id, title, invite_link)
            SELECT ?, id, channel_id, title, invite_link
            FROM channels
            """,
            (reset_id,),
        )
        await db.execute(
            """
            INSERT INTO contest_reset_promocodes (
                reset_id,
                original_id,
                code,
                channel_id,
                used_by,
                activated_at
            )
            SELECT ?, id, code, channel_id, used_by, activated_at
            FROM promocodes
            """,
            (reset_id,),
        )
        await db.execute(
            """
            INSERT INTO contest_reset_temporary_admins (
                reset_id,
                user_id,
                username,
                first_name,
                added_by,
                created_at,
                revoked_at
            )
            SELECT ?, user_id, username, first_name, added_by, created_at, revoked_at
            FROM temporary_admins
            """,
            (reset_id,),
        )

        await db.execute("UPDATE users SET tickets = 0, last_check_at = NULL")
        await db.execute("DELETE FROM winners")
        await db.execute("DELETE FROM casino_spins")
        await db.execute("DELETE FROM channels")
        await db.execute("DELETE FROM promocodes")
        await db.execute("DELETE FROM temporary_admins")

        await db.commit()
        return {"reset_id": reset_id, **preview}
    except Exception:
        await db.rollback()
        raise


async def get_contest_reset_runs(limit: int = 10) -> list[aiosqlite.Row]:
    """Получить последние owner reset runs."""
    db = await get_db()
    async with db.execute(
        """
        SELECT *
        FROM contest_reset_runs
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ) as cursor:
        return await cursor.fetchall()


# ════════════════════════════════════════════════════════════
#  CASINO
# ════════════════════════════════════════════════════════════

_CASINO_RESULTS = frozenset({"loss", "win", "jackpot"})


async def has_user_flag(user_id: int, flag: str) -> bool:
    """Проверить, установлен ли у пользователя служебный флаг."""
    db = await get_db()
    async with db.execute(
        "SELECT 1 FROM user_flags WHERE user_id = ? AND flag = ? LIMIT 1",
        (user_id, flag),
    ) as cursor:
        return (await cursor.fetchone()) is not None


async def set_user_flag(user_id: int, flag: str) -> None:
    """Установить служебный флаг пользователя (идемпотентно)."""
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO user_flags (user_id, flag) VALUES (?, ?)",
        (user_id, flag),
    )
    await db.commit()


async def get_user_casino_daily_spins(
    user_id: int,
    day_start_utc: datetime,
    day_end_utc: datetime,
) -> int:
    """
    Подсчитать число спинов пользователя в пределах суток [start, end) UTC.
    """
    db = await get_db()
    async with db.execute(
        """
        SELECT COUNT(*)
        FROM casino_spins
        WHERE user_id = ?
          AND created_at >= ?
          AND created_at < ?
        """,
        (user_id, to_sqlite_utc(day_start_utc), to_sqlite_utc(day_end_utc)),
    ) as cursor:
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


async def play_casino_spin_atomic(
    user_id: int,
    bet_amount: float,
    dice_value: int,
    result_type: str,
    multiplier: float,
) -> dict[str, float | int | str]:
    """
    Выполнить атомарный спин казино и обновить баланс пользователя.

    Транзакция выполняется строго через BEGIN IMMEDIATE.
    """
    if result_type not in _CASINO_RESULTS:
        raise ValueError("invalid_result_type")
    if bet_amount <= 0:
        raise ValueError("invalid_bet_amount")
    if dice_value < 1 or dice_value > 64:
        raise ValueError("invalid_dice_value")

    db = await get_db()
    await db.execute("BEGIN IMMEDIATE")

    try:
        async with db.execute(
            "SELECT tickets FROM users WHERE id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            raise ValueError("user_not_found")

        balance_before = float(row["tickets"] or 0.0)

        # Гарантируем, что после выбора ставки у пользователя остаётся >= 1 билет.
        if balance_before < bet_amount or (balance_before - bet_amount) < 1.0:
            raise ValueError("insufficient_balance")

        payout_amount = bet_amount * multiplier
        balance_after = balance_before - bet_amount + payout_amount

        await db.execute(
            "UPDATE users SET tickets = ? WHERE id = ?",
            (balance_after, user_id),
        )

        await db.execute(
            """
            INSERT INTO casino_spins (
                user_id,
                bet_amount,
                dice_value,
                result_type,
                multiplier,
                balance_before,
                balance_after
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                bet_amount,
                dice_value,
                result_type,
                multiplier,
                balance_before,
                balance_after,
            ),
        )

        await db.commit()
        return {
            "user_id": user_id,
            "bet_amount": bet_amount,
            "dice_value": dice_value,
            "result_type": result_type,
            "multiplier": multiplier,
            "balance_before": balance_before,
            "balance_after": balance_after,
            "payout_amount": payout_amount,
            "net_profit": payout_amount - bet_amount,
        }

    except Exception:
        await db.rollback()
        raise


async def get_casino_stats(
    day_start_utc: datetime,
    day_end_utc: datetime,
) -> dict[str, Any]:
    """Собрать статистику казино для админ-команды /casino_stats."""
    db = await get_db()

    start_sql = to_sqlite_utc(day_start_utc)
    end_sql = to_sqlite_utc(day_end_utc)

    async with db.execute("SELECT COUNT(*) FROM casino_spins") as cursor:
        total_spins = int((await cursor.fetchone())[0] or 0)

    async with db.execute(
        """
        SELECT COUNT(*)
        FROM casino_spins
        WHERE created_at >= ? AND created_at < ?
        """,
        (start_sql, end_sql),
    ) as cursor:
        today_spins = int((await cursor.fetchone())[0] or 0)

    async with db.execute(
        """
        SELECT
            COALESCE(SUM(bet_amount), 0),
            COALESCE(SUM(bet_amount * multiplier), 0)
        FROM casino_spins
        """
    ) as cursor:
        total_bets, total_payouts = await cursor.fetchone()

    async with db.execute(
        """
        SELECT
            COALESCE(SUM(bet_amount), 0),
            COALESCE(SUM(bet_amount * multiplier), 0)
        FROM casino_spins
        WHERE created_at >= ? AND created_at < ?
        """,
        (start_sql, end_sql),
    ) as cursor:
        today_bets, today_payouts = await cursor.fetchone()

    result_breakdown = {"loss": 0, "win": 0, "jackpot": 0}
    async with db.execute(
        "SELECT result_type, COUNT(*) AS cnt FROM casino_spins GROUP BY result_type"
    ) as cursor:
        rows = await cursor.fetchall()
        for row in rows:
            result_type = row["result_type"]
            if result_type in result_breakdown:
                result_breakdown[result_type] = int(row["cnt"])

    async with db.execute(
        """
        SELECT
            cs.user_id,
            u.username,
            u.first_name,
            COUNT(*) AS spins
        FROM casino_spins cs
        LEFT JOIN users u ON u.id = cs.user_id
        GROUP BY cs.user_id
        ORDER BY spins DESC, cs.user_id ASC
        LIMIT 3
        """
    ) as cursor:
        top_rows = await cursor.fetchall()

    top_players: list[dict[str, Any]] = []
    for row in top_rows:
        display_name = row["first_name"] or str(row["user_id"])
        if row["username"]:
            display_name = f"@{row['username']}"

        top_players.append(
            {
                "user_id": row["user_id"],
                "display_name": display_name,
                "spins": int(row["spins"]),
            }
        )

    win_spins = result_breakdown["win"] + result_breakdown["jackpot"]
    win_rate = (win_spins / total_spins * 100.0) if total_spins else 0.0

    total_bets_f = float(total_bets or 0.0)
    total_payouts_f = float(total_payouts or 0.0)
    today_bets_f = float(today_bets or 0.0)
    today_payouts_f = float(today_payouts or 0.0)

    return {
        "today_spins": today_spins,
        "total_spins": total_spins,
        "today_bets": today_bets_f,
        "today_payouts": today_payouts_f,
        "total_bets": total_bets_f,
        "total_payouts": total_payouts_f,
        "house_profit": total_bets_f - total_payouts_f,
        "win_rate": win_rate,
        "breakdown": result_breakdown,
        "top_players": top_players,
    }
