"""
Тесты для Этапа 1: Инициализация проекта и БД.

Проверяет:
1. Корректность создания всех таблиц.
2. Правильность конфигурации (загрузка переменных).
3. CRUD-операции на уровне моделей.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import aiosqlite

# Добавляем корень проекта в sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ──────────────────── Мок .env для тестов ────────────────────
# Устанавливаем переменные ДО импорта config, чтобы _require_env не падал
_TEST_ENV = {
    "BOT_TOKEN": "123456:TEST_TOKEN_FOR_TESTS",
    "ADMIN_IDS": "111,222",
    "BOT_USERNAME": "TestContestBot",
}

for k, v in _TEST_ENV.items():
    os.environ.setdefault(k, v)

# SQL-схема продублирована напрямую для тестов (не зависит от config)
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY,
    username        TEXT,
    first_name      TEXT,
    last_name       TEXT,
    language_code   TEXT    DEFAULT 'ru',
    is_premium      BOOLEAN DEFAULT FALSE,
    ref_link        TEXT    UNIQUE,
    ref_by          INTEGER,
    tickets         REAL    DEFAULT 0.0,
    registered_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_check_at   TIMESTAMP,
    blocked_bot     BOOLEAN DEFAULT FALSE,
    FOREIGN KEY(ref_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS channels (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id   TEXT UNIQUE,
    title        TEXT,
    invite_link  TEXT
);

CREATE TABLE IF NOT EXISTS promocodes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    code         TEXT UNIQUE,
    channel_id   INTEGER,
    used_by      INTEGER,
    activated_at TIMESTAMP,
    FOREIGN KEY(used_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS referrals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_id  INTEGER,
    referred_id  INTEGER,
    status       TEXT CHECK(status IN ('pending','completed','rejected')),
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(referrer_id) REFERENCES users(id),
    FOREIGN KEY(referred_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS winners (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER,
    prize     TEXT NOT NULL,
    draw_date TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS contest_prizes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    position   INTEGER NOT NULL,
    name       TEXT    NOT NULL,
    quantity   INTEGER NOT NULL CHECK(quantity > 0),
    created_by INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    key       TEXT PRIMARY KEY,
    value     TEXT
);
"""


class TestDatabaseSchema(unittest.TestCase):
    """Тесты создания схемы БД."""

    def setUp(self) -> None:
        self.tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp_file.name
        self.tmp_file.close()

    def tearDown(self) -> None:
        os.unlink(self.db_path)

    def test_all_tables_created(self) -> None:
        """Базовые таблицы создаются корректно."""
        async def _run() -> None:
            async with aiosqlite.connect(self.db_path) as db:
                await db.executescript(_SCHEMA_SQL)
                await db.commit()

                async with db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ) as cursor:
                    tables = [row[0] for row in await cursor.fetchall()]

                expected = ["channels", "contest_prizes", "promocodes", "referrals", "settings", "users", "winners"]
                self.assertEqual(tables, expected)

        asyncio.run(_run())

    def test_users_table_columns(self) -> None:
        """Таблица users содержит все необходимые столбцы."""
        async def _run() -> None:
            async with aiosqlite.connect(self.db_path) as db:
                await db.executescript(_SCHEMA_SQL)

                async with db.execute("PRAGMA table_info(users)") as cursor:
                    columns = {row[1] for row in await cursor.fetchall()}

                expected_columns = {
                    "id", "username", "first_name", "last_name",
                    "language_code", "is_premium", "ref_link", "ref_by",
                    "tickets", "registered_at", "last_check_at", "blocked_bot",
                }
                self.assertEqual(columns, expected_columns)

        asyncio.run(_run())

    def test_wal_mode(self) -> None:
        """WAL режим включается корректно."""
        async def _run() -> None:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("PRAGMA journal_mode=WAL;")
                async with db.execute("PRAGMA journal_mode;") as cursor:
                    row = await cursor.fetchone()
                    self.assertEqual(row[0], "wal")

        asyncio.run(_run())

    def test_winners_accept_custom_prizes(self) -> None:
        """winners.prize принимает произвольные названия призов."""
        async def _run() -> None:
            async with aiosqlite.connect(self.db_path) as db:
                await db.executescript(_SCHEMA_SQL)
                await db.execute(
                    "INSERT INTO users (id, ref_link) VALUES (1, 'abc')"
                )
                await db.execute(
                    "INSERT INTO winners (user_id, prize) VALUES (1, 'Custom Prize')"
                )
                await db.commit()

                async with db.execute("SELECT prize FROM winners WHERE user_id = 1") as cursor:
                    row = await cursor.fetchone()
                self.assertEqual(row[0], "Custom Prize")

        asyncio.run(_run())


class TestCRUDOperations(unittest.TestCase):
    """Тесты CRUD-операций через models.py."""

    def setUp(self) -> None:
        self.tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp_file.name
        self.tmp_file.close()

    def tearDown(self) -> None:
        os.unlink(self.db_path)

    def _make_conn(self):
        """Создать и настроить тестовое соединение."""
        async def _setup() -> aiosqlite.Connection:
            conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
            await conn.execute("PRAGMA journal_mode=WAL;")
            await conn.execute("PRAGMA foreign_keys=ON;")
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA_SQL)
            await conn.commit()
            return conn
        return asyncio.get_event_loop().run_until_complete(_setup())

    def test_create_and_get_user(self) -> None:
        """Создание и получение пользователя."""
        async def _run() -> None:
            import db.database as database_mod
            conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
            await conn.execute("PRAGMA journal_mode=WAL;")
            await conn.execute("PRAGMA foreign_keys=ON;")
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA_SQL)
            await conn.commit()
            database_mod._connection = conn

            try:
                from db.models import create_user, get_user

                await create_user(
                    user_id=123456,
                    username="testuser",
                    first_name="Test",
                    last_name="User",
                    language_code="ru",
                    is_premium=False,
                    ref_link="abc123",
                    ref_by=None,
                )

                user = await get_user(123456)
                self.assertIsNotNone(user)
                self.assertEqual(user["username"], "testuser")
                self.assertEqual(user["language_code"], "ru")
                self.assertEqual(user["tickets"], 0.0)
                self.assertFalse(user["is_premium"])
            finally:
                await conn.close()
                database_mod._connection = None

        asyncio.run(_run())

    def test_add_tickets(self) -> None:
        """Начисление билетов пользователю."""
        async def _run() -> None:
            import db.database as database_mod
            conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
            await conn.execute("PRAGMA journal_mode=WAL;")
            await conn.execute("PRAGMA foreign_keys=ON;")
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA_SQL)
            await conn.commit()
            database_mod._connection = conn

            try:
                from db.models import add_user_tickets, create_user, get_user

                await create_user(
                    user_id=789,
                    username="ticketuser",
                    first_name="Ticket",
                    last_name="User",
                    language_code="uk",
                    is_premium=True,
                    ref_link="tkt789",
                )

                await add_user_tickets(789, 2.0)
                user = await get_user(789)
                self.assertEqual(user["tickets"], 2.0)

                await add_user_tickets(789, 5.0)
                user = await get_user(789)
                self.assertEqual(user["tickets"], 7.0)
            finally:
                await conn.close()
                database_mod._connection = None

        asyncio.run(_run())

    def test_create_referral(self) -> None:
        """Создание реферальной записи и обновление статуса."""
        async def _run() -> None:
            import db.database as database_mod
            conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
            await conn.execute("PRAGMA journal_mode=WAL;")
            await conn.execute("PRAGMA foreign_keys=ON;")
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA_SQL)
            await conn.commit()
            database_mod._connection = conn

            try:
                from db.models import (
                    count_completed_referrals,
                    create_referral,
                    create_user,
                    get_pending_referral,
                    update_referral_status,
                )

                await create_user(111, "user1", "A", "B", "ru", False, "ref1")
                await create_user(222, "user2", "C", "D", "ru", False, "ref2", ref_by=111)

                await create_referral(referrer_id=111, referred_id=222)

                pending = await get_pending_referral(222)
                self.assertIsNotNone(pending)
                self.assertEqual(pending["status"], "pending")

                await update_referral_status(111, 222, "completed")
                count = await count_completed_referrals(111)
                self.assertEqual(count, 1)
            finally:
                await conn.close()
                database_mod._connection = None

        asyncio.run(_run())


class TestConfig(unittest.TestCase):
    """Тесты конфигурации."""

    def test_blacklist_languages(self) -> None:
        """Чёрный список языков содержит все 10 языков."""
        from config import BLACKLIST_LANG
        expected = {"ar", "fa", "hi", "ur", "bn", "th", "vi", "zh", "ja", "ko"}
        self.assertEqual(BLACKLIST_LANG, expected)
        self.assertEqual(len(BLACKLIST_LANG), 10)

    def test_paths_exist(self) -> None:
        """Критические пути определены."""
        from config import BASE_DIR, DB_PATH, LOCALES_DIR, LOGS_DIR
        self.assertTrue(BASE_DIR.exists())
        self.assertTrue(LOCALES_DIR.exists())
        self.assertTrue(LOGS_DIR.exists())
        self.assertTrue(str(DB_PATH).endswith("contest.db"))

    def test_admin_ids_parsed(self) -> None:
        """ADMIN_IDS парсятся как список int."""
        from config import ADMIN_IDS
        self.assertIsInstance(ADMIN_IDS, list)
        self.assertTrue(all(isinstance(i, int) for i in ADMIN_IDS))


if __name__ == "__main__":
    unittest.main()
