"""
Асинхронное подключение к SQLite и инициализация схемы БД.

Используется aiosqlite с режимом WAL для конкурентного доступа.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import aiosqlite

from config import DB_PATH

logger = logging.getLogger(__name__)

# Глобальное соединение (singleton)
_connection: Optional[aiosqlite.Connection] = None


# ──────────────────── SQL-схема ────────────────────

_SCHEMA_SQL = """
-- users: участники конкурса
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY,          -- Telegram ID
    username        TEXT,
    first_name      TEXT,
    last_name       TEXT,
    language_code   TEXT    DEFAULT 'ru',          -- 'ru' или 'uk'
    is_premium      BOOLEAN DEFAULT FALSE,
    ref_link        TEXT    UNIQUE,                -- уникальная реф-ссылка (base64)
    ref_by          INTEGER,                      -- кто пригласил (ID)
    tickets         REAL    DEFAULT 0.0,           -- кол-во билетов
    registered_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_check_at   TIMESTAMP,
    blocked_bot     BOOLEAN DEFAULT FALSE,
    FOREIGN KEY(ref_by) REFERENCES users(id)
);

-- channels: обязательные каналы для подписки
CREATE TABLE IF NOT EXISTS channels (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id   TEXT UNIQUE,                      -- '-100...'
    title        TEXT,
    invite_link  TEXT                               -- https://t.me/...
);

-- promocodes: пасхалки (одноразовые глобально)
CREATE TABLE IF NOT EXISTS promocodes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    code         TEXT UNIQUE,
    channel_id   INTEGER,                          -- привязка к каналу (опционально)
    used_by      INTEGER,
    activated_at TIMESTAMP,
    FOREIGN KEY(used_by) REFERENCES users(id)
);

-- referrals: история приглашений
CREATE TABLE IF NOT EXISTS referrals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_id  INTEGER,
    referred_id  INTEGER,
    status       TEXT CHECK(status IN ('pending','completed','rejected')),
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(referrer_id) REFERENCES users(id),
    FOREIGN KEY(referred_id) REFERENCES users(id)
);

-- winners: результаты розыгрыша
CREATE TABLE IF NOT EXISTS winners (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER,
    prize     TEXT CHECK(prize IN ('MacBook Neo', 'AirPods 3 Pro')),
    draw_date TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

-- settings: настройки бота (хранение даты окончания)
CREATE TABLE IF NOT EXISTS settings (
    key       TEXT PRIMARY KEY,
    value     TEXT
);

-- casino_spins: история спинов в модуле "Казик"
CREATE TABLE IF NOT EXISTS casino_spins (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    bet_amount     REAL NOT NULL,
    dice_value     INTEGER NOT NULL,
    result_type    TEXT CHECK(result_type IN ('loss', 'win', 'jackpot')),
    multiplier     REAL NOT NULL,
    balance_before REAL NOT NULL,
    balance_after  REAL NOT NULL,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_casino_daily ON casino_spins(user_id, created_at);

-- user_flags: служебные пользовательские флаги (например, дисклеймер казино)
CREATE TABLE IF NOT EXISTS user_flags (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    flag       TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, flag),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_user_flags_lookup ON user_flags(user_id, flag);

-- temporary_admins: временные админы арендаторов/конкурсов
CREATE TABLE IF NOT EXISTS temporary_admins (
    user_id    INTEGER PRIMARY KEY,
    username   TEXT,
    first_name TEXT,
    added_by   INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_temporary_admins_active ON temporary_admins(revoked_at);

-- admin_audit_log: аудит действий owner/temp admin
CREATE TABLE IF NOT EXISTS admin_audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id   INTEGER NOT NULL,
    action     TEXT NOT NULL,
    target_id  INTEGER,
    payload    TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_admin_audit_actor ON admin_audit_log(actor_id, created_at);
CREATE INDEX IF NOT EXISTS idx_admin_audit_action ON admin_audit_log(action, created_at);

-- contest_reset_runs: история owner-сбросов конкурса
CREATE TABLE IF NOT EXISTS contest_reset_runs (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id                   INTEGER NOT NULL,
    created_at                 TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    users_with_tickets_count   INTEGER NOT NULL DEFAULT 0,
    total_tickets              REAL    NOT NULL DEFAULT 0.0,
    winners_count              INTEGER NOT NULL DEFAULT 0,
    casino_spins_count         INTEGER NOT NULL DEFAULT 0,
    channels_count             INTEGER NOT NULL DEFAULT 0,
    promocodes_count           INTEGER NOT NULL DEFAULT 0,
    active_temp_admins_count   INTEGER NOT NULL DEFAULT 0,
    temp_admins_count          INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_contest_reset_runs_created ON contest_reset_runs(created_at);

-- contest_reset_user_tickets: архив балансов пользователей перед reset
CREATE TABLE IF NOT EXISTS contest_reset_user_tickets (
    reset_id      INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    username      TEXT,
    first_name    TEXT,
    last_name     TEXT,
    language_code TEXT,
    is_premium    BOOLEAN,
    ref_link      TEXT,
    ref_by        INTEGER,
    tickets       REAL,
    registered_at TIMESTAMP,
    last_check_at TIMESTAMP,
    blocked_bot   BOOLEAN,
    FOREIGN KEY(reset_id) REFERENCES contest_reset_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_contest_reset_user_tickets_reset ON contest_reset_user_tickets(reset_id);

-- contest_reset_winners: архив winners перед reset
CREATE TABLE IF NOT EXISTS contest_reset_winners (
    reset_id    INTEGER NOT NULL,
    original_id INTEGER NOT NULL,
    user_id     INTEGER,
    prize       TEXT,
    draw_date   TIMESTAMP,
    FOREIGN KEY(reset_id) REFERENCES contest_reset_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_contest_reset_winners_reset ON contest_reset_winners(reset_id);

-- contest_reset_casino_spins: архив casino_spins перед reset
CREATE TABLE IF NOT EXISTS contest_reset_casino_spins (
    reset_id       INTEGER NOT NULL,
    original_id    INTEGER NOT NULL,
    user_id        INTEGER NOT NULL,
    bet_amount     REAL NOT NULL,
    dice_value     INTEGER NOT NULL,
    result_type    TEXT,
    multiplier     REAL NOT NULL,
    balance_before REAL NOT NULL,
    balance_after  REAL NOT NULL,
    created_at     TIMESTAMP,
    FOREIGN KEY(reset_id) REFERENCES contest_reset_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_contest_reset_casino_spins_reset ON contest_reset_casino_spins(reset_id);

-- contest_reset_channels: архив channels перед reset
CREATE TABLE IF NOT EXISTS contest_reset_channels (
    reset_id    INTEGER NOT NULL,
    original_id INTEGER NOT NULL,
    channel_id  TEXT,
    title       TEXT,
    invite_link TEXT,
    FOREIGN KEY(reset_id) REFERENCES contest_reset_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_contest_reset_channels_reset ON contest_reset_channels(reset_id);

-- contest_reset_promocodes: архив promocodes перед reset
CREATE TABLE IF NOT EXISTS contest_reset_promocodes (
    reset_id     INTEGER NOT NULL,
    original_id  INTEGER NOT NULL,
    code         TEXT,
    channel_id   INTEGER,
    used_by      INTEGER,
    activated_at TIMESTAMP,
    FOREIGN KEY(reset_id) REFERENCES contest_reset_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_contest_reset_promocodes_reset ON contest_reset_promocodes(reset_id);

-- contest_reset_temporary_admins: архив temporary_admins перед reset
CREATE TABLE IF NOT EXISTS contest_reset_temporary_admins (
    reset_id   INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    username   TEXT,
    first_name TEXT,
    added_by   INTEGER NOT NULL,
    created_at TIMESTAMP,
    revoked_at TIMESTAMP,
    FOREIGN KEY(reset_id) REFERENCES contest_reset_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_contest_reset_temporary_admins_reset ON contest_reset_temporary_admins(reset_id);
"""


async def get_db() -> aiosqlite.Connection:
    """
    Получить глобальное соединение с БД.

    При первом вызове создаёт соединение, включает WAL и foreign keys.
    """
    global _connection

    if _connection is None:
        logger.info("Подключение к БД: %s", DB_PATH)
        _connection = await aiosqlite.connect(
            str(DB_PATH),
            check_same_thread=False,
        )
        # Включаем WAL для лучшей конкурентности
        await _connection.execute("PRAGMA journal_mode=WAL;")
        # Включаем проверку внешних ключей
        await _connection.execute("PRAGMA foreign_keys=ON;")
        # Возвращать строки как sqlite3.Row для доступа по имени столбца
        _connection.row_factory = aiosqlite.Row
        logger.info("WAL и foreign_keys включены.")

    return _connection


async def init_db() -> None:
    """
    Инициализировать схему БД: создать все таблицы, если они отсутствуют.
    """
    db = await get_db()
    await db.executescript(_SCHEMA_SQL)
    await db.commit()
    logger.info("Схема БД инициализирована успешно.")


async def close_db() -> None:
    """
    Закрыть соединение с БД.
    """
    global _connection
    if _connection is not None:
        await _connection.close()
        _connection = None
        logger.info("Соединение с БД закрыто.")
