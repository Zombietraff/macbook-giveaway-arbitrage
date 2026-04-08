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
