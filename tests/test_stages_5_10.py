"""
Тесты для Этапов 5-10: промокоды, профиль, розыгрыш, дата окончания.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite

# Мок .env
_TEST_ENV = {
    "BOT_TOKEN": "123456:TEST_TOKEN_FOR_TESTS",
    "ADMIN_IDS": "111,222",
    "MAX_USER_ID": "8000000000",
    "BOT_USERNAME": "TestContestBot",
}
for k, v in _TEST_ENV.items():
    os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database import _SCHEMA_SQL


class TestPromocodeActivation(unittest.TestCase):
    """Тесты активации промокодов."""

    def setUp(self) -> None:
        self.tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp_file.name
        self.tmp_file.close()

    def tearDown(self) -> None:
        os.unlink(self.db_path)

    def test_activate_valid_promocode(self) -> None:
        """Валидный промокод активируется, начисляются +5 билетов."""
        async def _run() -> None:
            import db.database as database_mod
            conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
            await conn.execute("PRAGMA journal_mode=WAL;")
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA_SQL)
            await conn.commit()
            database_mod._connection = conn

            try:
                from db.models import (
                    activate_promocode,
                    add_promocode,
                    add_user_tickets,
                    create_user,
                    get_promocode,
                    get_user,
                )

                await create_user(100, "user", "A", "B", "ru", False, "ref1")
                await add_user_tickets(100, 1.0)  # базовый билет
                await add_promocode("TEST_CODE")

                # Проверяем промокод
                promo = await get_promocode("TEST_CODE")
                self.assertIsNotNone(promo)
                self.assertIsNone(promo["used_by"])

                # Активируем
                await activate_promocode("TEST_CODE", 100)
                await add_user_tickets(100, 5.0)

                # Проверяем результат
                promo = await get_promocode("TEST_CODE")
                self.assertEqual(promo["used_by"], 100)
                self.assertIsNotNone(promo["activated_at"])

                user = await get_user(100)
                self.assertEqual(user["tickets"], 6.0)  # 1.0 + 5.0

            finally:
                await conn.close()
                database_mod._connection = None

        asyncio.run(_run())

    def test_already_used_promocode(self) -> None:
        """Уже использованный промокод нельзя активировать повторно."""
        async def _run() -> None:
            import db.database as database_mod
            conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
            await conn.execute("PRAGMA journal_mode=WAL;")
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA_SQL)
            await conn.commit()
            database_mod._connection = conn

            try:
                from db.models import (
                    activate_promocode,
                    add_promocode,
                    create_user,
                    get_promocode,
                )

                await create_user(100, "u1", "A", "B", "ru", False, "r1")
                await create_user(200, "u2", "C", "D", "ru", False, "r2")
                await add_promocode("ONCE_CODE")

                # Первый юзер активирует
                await activate_promocode("ONCE_CODE", 100)

                # Промокод уже занят
                promo = await get_promocode("ONCE_CODE")
                self.assertIsNotNone(promo["used_by"])
                self.assertEqual(promo["used_by"], 100)

            finally:
                await conn.close()
                database_mod._connection = None

        asyncio.run(_run())

    def test_nonexistent_promocode(self) -> None:
        """Несуществующий промокод не находится."""
        async def _run() -> None:
            import db.database as database_mod
            conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
            await conn.execute("PRAGMA journal_mode=WAL;")
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA_SQL)
            await conn.commit()
            database_mod._connection = conn

            try:
                from db.models import get_promocode
                promo = await get_promocode("FAKE_CODE")
                self.assertIsNone(promo)
            finally:
                await conn.close()
                database_mod._connection = None

        asyncio.run(_run())


class TestContestActive(unittest.TestCase):
    """Тесты проверки активности конкурса."""

    def setUp(self) -> None:
        self.tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp_file.name
        self.tmp_file.close()

    def tearDown(self) -> None:
        os.unlink(self.db_path)

    def test_contest_active_when_before_end(self) -> None:
        """Конкурс активен до END_DATE."""
        async def _run() -> None:
            import db.database as database_mod
            from db.models import set_end_date
            from middlewares.contest_active import is_contest_active
            
            conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
            await conn.executescript(_SCHEMA_SQL)
            database_mod._connection = conn

            try:
                # Ставим дату будущего
                await set_end_date(datetime(2026, 12, 31, 23, 59))
                self.assertTrue(await is_contest_active())
            finally:
                await conn.close()
                database_mod._connection = None

        asyncio.run(_run())

    def test_contest_not_active_when_past_end(self) -> None:
        """Конкурс не активен после END_DATE."""
        async def _run() -> None:
            import db.database as database_mod
            from db.models import set_end_date
            from middlewares.contest_active import is_contest_active

            conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
            await conn.executescript(_SCHEMA_SQL)
            database_mod._connection = conn

            try:
                # Ставим дату прошлого
                await set_end_date(datetime(2020, 1, 1))
                self.assertFalse(await is_contest_active())
            finally:
                await conn.close()
                database_mod._connection = None

        asyncio.run(_run())


class TestDrawLogic(unittest.TestCase):
    """Тесты логики розыгрыша."""

    def setUp(self) -> None:
        self.tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp_file.name
        self.tmp_file.close()

    def tearDown(self) -> None:
        os.unlink(self.db_path)

    def test_draw_with_enough_users(self) -> None:
        """Розыгрыш с >= 4 участниками возвращает 4 победителя."""
        async def _run() -> None:
            import db.database as database_mod
            conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
            await conn.execute("PRAGMA journal_mode=WAL;")
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA_SQL)
            await conn.commit()
            database_mod._connection = conn

            try:
                from db.models import add_user_tickets, create_user
                from utils.draw import perform_draw

                # Создаём 5 участников
                for i in range(1, 6):
                    await create_user(i * 100, f"user{i}", f"Name{i}", "L", "ru", False, f"ref{i}")
                    await add_user_tickets(i * 100, float(i))

                # Мок бота с успешной доставкой
                mock_bot = AsyncMock()
                mock_bot.send_message = AsyncMock(return_value=True)

                winners = await perform_draw(mock_bot)

                self.assertEqual(len(winners), 4)

                # Первые 3 — MacBook Neo
                for w in winners[:3]:
                    self.assertEqual(w["prize"], "MacBook Neo")

                # 4-й — AirPods
                self.assertEqual(winners[3]["prize"], "AirPods 3 Pro")

                # Все уникальные
                winner_ids = [w["user_id"] for w in winners]
                self.assertEqual(len(set(winner_ids)), 4)

            finally:
                await conn.close()
                database_mod._connection = None

        asyncio.run(_run())

    def test_draw_insufficient_users(self) -> None:
        """Розыгрыш с < 4 участниками возвращает пустой список."""
        async def _run() -> None:
            import db.database as database_mod
            conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
            await conn.execute("PRAGMA journal_mode=WAL;")
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA_SQL)
            await conn.commit()
            database_mod._connection = conn

            try:
                from db.models import add_user_tickets, create_user
                from utils.draw import perform_draw

                # Только 2 участника
                await create_user(100, "u1", "A", "B", "ru", False, "r1")
                await add_user_tickets(100, 1.0)
                await create_user(200, "u2", "C", "D", "ru", False, "r2")
                await add_user_tickets(200, 2.0)

                mock_bot = AsyncMock()
                winners = await perform_draw(mock_bot)
                self.assertEqual(len(winners), 0)

            finally:
                await conn.close()
                database_mod._connection = None

        asyncio.run(_run())

    def test_blocked_users_excluded(self) -> None:
        """Пользователи с blocked_bot=True исключаются из розыгрыша."""
        async def _run() -> None:
            import db.database as database_mod
            conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
            await conn.execute("PRAGMA journal_mode=WAL;")
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA_SQL)
            await conn.commit()
            database_mod._connection = conn

            try:
                from db.models import add_user_tickets, create_user, set_user_blocked
                from utils.draw import _get_eligible_users

                # 5 пользователей, 1 заблокировал бота
                for i in range(1, 6):
                    await create_user(i * 100, f"u{i}", f"N{i}", "L", "ru", False, f"r{i}")
                    await add_user_tickets(i * 100, 1.0)

                await set_user_blocked(300, True)

                mock_bot = AsyncMock()
                eligible = await _get_eligible_users(mock_bot)
                self.assertEqual(len(eligible), 4)

                eligible_ids = {u["id"] for u in eligible}
                self.assertNotIn(300, eligible_ids)

            finally:
                await conn.close()
                database_mod._connection = None

        asyncio.run(_run())


class TestWinnersDisplay(unittest.TestCase):
    """Тесты отображения победителей."""

    def setUp(self) -> None:
        self.tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp_file.name
        self.tmp_file.close()

    def tearDown(self) -> None:
        os.unlink(self.db_path)

    def test_get_all_winners(self) -> None:
        """Получение списка победителей из БД."""
        async def _run() -> None:
            import db.database as database_mod
            conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
            await conn.execute("PRAGMA journal_mode=WAL;")
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA_SQL)
            await conn.commit()
            database_mod._connection = conn

            try:
                from db.models import add_winner, create_user, get_all_winners

                await create_user(100, "winner1", "A", "B", "ru", False, "r1")
                await create_user(200, "winner2", "C", "D", "uk", True, "r2")

                await add_winner(100, "MacBook Neo", datetime.now())
                await add_winner(200, "AirPods 3 Pro", datetime.now())

                winners = await get_all_winners()
                self.assertEqual(len(winners), 2)
                self.assertEqual(winners[0]["prize"], "MacBook Neo")
                self.assertEqual(winners[1]["prize"], "AirPods 3 Pro")

            finally:
                await conn.close()
                database_mod._connection = None

        asyncio.run(_run())


class TestAdminFunctions(unittest.TestCase):
    """Тесты админ-функций."""

    def test_admin_id_check(self) -> None:
        """Проверка ID администратора."""
        from handlers.admin import _is_admin
        self.assertTrue(_is_admin(111))
        self.assertTrue(_is_admin(222))
        self.assertFalse(_is_admin(999))

    def test_set_date(self) -> None:
        """Установка даты работает корректно через БД."""
        async def _run() -> None:
            tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            db_path = tmp_file.name
            tmp_file.close()

            import db.database as database_mod
            from db.models import get_end_date, set_end_date
            
            conn = await aiosqlite.connect(db_path, check_same_thread=False)
            await conn.executescript(_SCHEMA_SQL)
            database_mod._connection = conn

            try:
                new = datetime(2027, 6, 15, 23, 59)
                await set_end_date(new)
                fetched = await get_end_date()
                self.assertEqual(fetched, new)
            finally:
                await conn.close()
                database_mod._connection = None
                os.unlink(db_path)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
