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

    def test_live_subscription_excludes_unsubscribed_users(self) -> None:
        """Пользователь без подписки на текущие каналы исключается из draw eligibility."""
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
                from utils.draw import _get_eligible_users

                for i in range(1, 5):
                    await create_user(i * 100, f"u{i}", f"N{i}", "L", "ru", False, f"live{i}")
                    await add_user_tickets(i * 100, 1.0)

                async def fake_check_subscription(bot, user_id):
                    if user_id == 200:
                        return False, [{"channel_id": "-1001"}]
                    return True, []

                mock_bot = AsyncMock()
                with patch("utils.draw.check_subscription", new=AsyncMock(side_effect=fake_check_subscription)):
                    eligible = await _get_eligible_users(mock_bot)

                eligible_ids = {u["id"] for u in eligible}
                self.assertEqual(len(eligible), 3)
                self.assertNotIn(200, eligible_ids)
            finally:
                await conn.close()
                database_mod._connection = None

        asyncio.run(_run())

    def test_hidden_trust_multiplier_changes_effective_draw_weight(self) -> None:
        """Trust x5 меняет скрытый draw weight, не меняя visible tickets."""
        async def _run() -> None:
            import db.database as database_mod
            conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
            await conn.execute("PRAGMA journal_mode=WAL;")
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA_SQL)
            await conn.commit()
            database_mod._connection = conn

            try:
                from db.models import add_user_tickets, create_user, set_user_trust_score
                from utils.draw import _get_eligible_users

                await create_user(100, "boosted", "Boost", "L", "ru", False, "trust100")
                await create_user(200, "plain", "Plain", "L", "ru", False, "trust200")
                await add_user_tickets(100, 1.0)
                await add_user_tickets(200, 1.0)
                await set_user_trust_score(100, common_chat_count=1)

                mock_bot = AsyncMock()
                with patch("utils.draw.check_subscription", new=AsyncMock(return_value=(True, []))):
                    eligible = await _get_eligible_users(mock_bot)

                by_id = {user["id"]: user for user in eligible}
                self.assertEqual(by_id[100]["tickets"], 1.0)
                self.assertEqual(by_id[100]["draw_multiplier"], 5.0)
                self.assertEqual(by_id[100]["effective_weight"], 5.0)
                self.assertEqual(by_id[200]["draw_multiplier"], 1.0)
                self.assertEqual(by_id[200]["effective_weight"], 1.0)
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
        async def _run() -> None:
            tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            db_path = tmp_file.name
            tmp_file.close()

            import config
            import db.database as database_mod
            from db.models import add_temporary_admin, revoke_temporary_admin
            from handlers.admin import _is_admin, _is_owner

            original_owner_ids = config.OWNER_IDS
            config.OWNER_IDS = [111, 222]

            conn = await aiosqlite.connect(db_path, check_same_thread=False)
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA_SQL)
            await conn.commit()
            database_mod._connection = conn

            try:
                self.assertTrue(_is_owner(111))
                self.assertTrue(_is_owner(222))
                self.assertFalse(_is_owner(999))

                self.assertTrue(await _is_admin(111))
                self.assertTrue(await _is_admin(222))
                self.assertFalse(await _is_admin(999))

                await add_temporary_admin(333, added_by=111, username="temp", first_name="Temp")
                self.assertTrue(await _is_admin(333))

                await revoke_temporary_admin(333)
                self.assertFalse(await _is_admin(333))
            finally:
                config.OWNER_IDS = original_owner_ids
                await conn.close()
                database_mod._connection = None
                os.unlink(db_path)

        asyncio.run(_run())

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

    def test_plugin_registry_and_active_setting(self) -> None:
        """Реестр плагинов находит cherry-charm и валидирует active_plugin_key."""
        async def _run() -> None:
            tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            db_path = tmp_file.name
            tmp_file.close()

            import db.database as database_mod
            from utils.plugins import get_active_plugin_key, list_plugins, set_active_plugin_key

            conn = await aiosqlite.connect(db_path, check_same_thread=False)
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA_SQL)
            await conn.commit()
            database_mod._connection = conn

            try:
                plugins = list_plugins()
                self.assertTrue(any(plugin.key == "cherry-charm" for plugin in plugins))
                self.assertEqual(await get_active_plugin_key(), "cherry-charm")

                plugin = await set_active_plugin_key("cherry-charm")
                self.assertEqual(plugin.key, "cherry-charm")
                self.assertEqual(await get_active_plugin_key(), "cherry-charm")

                with self.assertRaises(ValueError):
                    await set_active_plugin_key("missing-plugin")
            finally:
                await conn.close()
                database_mod._connection = None
                os.unlink(db_path)

        asyncio.run(_run())

    def test_trust_score_multiplier_logic(self) -> None:
        """Common groups map to hidden x1/x5 multipliers."""
        async def _run() -> None:
            tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            db_path = tmp_file.name
            tmp_file.close()

            import db.database as database_mod
            from db.models import (
                calculate_trust_multiplier,
                create_user,
                get_trust_stats,
                get_user_draw_multiplier,
                get_user_trust_score,
                set_user_trust_score,
            )

            conn = await aiosqlite.connect(db_path, check_same_thread=False)
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA_SQL)
            await conn.commit()
            database_mod._connection = conn

            try:
                self.assertEqual(calculate_trust_multiplier(0), 1.0)
                self.assertEqual(calculate_trust_multiplier(1), 5.0)
                self.assertEqual(calculate_trust_multiplier(3), 5.0)

                await create_user(100, "plain", "Plain", "T", "ru", False, "trust_plain")
                await create_user(200, "boosted", "Boost", "T", "ru", False, "trust_boost")
                await set_user_trust_score(100, common_chat_count=0)
                await set_user_trust_score(200, common_chat_count=3)

                self.assertEqual(await get_user_draw_multiplier(100), 1.0)
                self.assertEqual(await get_user_draw_multiplier(200), 5.0)
                boosted = await get_user_trust_score(200)
                self.assertEqual(boosted["status"], "boosted")
                self.assertEqual(boosted["common_chat_count"], 3)

                stats = await get_trust_stats()
                self.assertEqual(stats["total"], 2)
                self.assertEqual(stats["plain"], 1)
                self.assertEqual(stats["boosted"], 1)
                self.assertEqual(stats["strong_common_3_plus"], 1)
            finally:
                await conn.close()
                database_mod._connection = None
                os.unlink(db_path)

        asyncio.run(_run())

    def test_reset_contest_archives_and_clears_selected_state(self) -> None:
        """Owner reset архивирует данные и очищает состояние нового конкурса."""
        async def _run() -> None:
            tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            db_path = tmp_file.name
            tmp_file.close()

            import db.database as database_mod
            from db.models import (
                add_admin_audit_log,
                add_channel,
                add_promocode,
                add_temporary_admin,
                add_user_tickets,
                add_winner,
                create_referral,
                create_user,
                get_trust_stats,
                get_contest_reset_preview,
                get_contest_reset_runs,
                get_setting,
                get_user,
                reset_contest_with_archive,
                set_setting,
                set_user_trust_score,
                set_user_flag,
            )

            conn = await aiosqlite.connect(db_path, check_same_thread=False)
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA_SQL)
            await conn.commit()
            database_mod._connection = conn

            try:
                await create_user(100, "u100", "A", "B", "ru", False, "reset100")
                await create_user(200, "u200", "C", "D", "ru", False, "reset200")
                await add_user_tickets(100, 3.0)
                await add_user_tickets(200, 2.0)
                await create_referral(100, 200)
                await set_user_flag(100, "keep_flag")
                await set_setting("active_plugin_key", "cherry-charm")
                await add_admin_audit_log(111, "before_reset")
                await set_user_trust_score(100, common_chat_count=1)

                await add_winner(100, "MacBook Neo", datetime.now())
                await add_channel("-1001", "Channel", "https://t.me/example")
                await add_promocode("RESET_CODE")
                await add_temporary_admin(333, added_by=111, username="temp", first_name="Temp")
                await conn.execute(
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
                    VALUES (100, 1, 1, 'loss', 0, 3, 2)
                    """
                )
                await conn.commit()

                preview = await get_contest_reset_preview()
                self.assertEqual(preview["users_with_tickets_count"], 2)
                self.assertEqual(preview["total_tickets"], 5.0)
                self.assertEqual(preview["winners_count"], 1)
                self.assertEqual(preview["casino_spins_count"], 1)
                self.assertEqual(preview["channels_count"], 1)
                self.assertEqual(preview["promocodes_count"], 1)
                self.assertEqual(preview["trust_scores_count"], 1)
                self.assertEqual(preview["active_temp_admins_count"], 1)

                result = await reset_contest_with_archive(actor_id=111)
                reset_id = int(result["reset_id"])
                self.assertGreater(reset_id, 0)

                user = await get_user(100)
                self.assertEqual(user["tickets"], 0)
                self.assertIsNone(user["last_check_at"])
                self.assertEqual(await get_setting("active_plugin_key"), "cherry-charm")

                checks = {
                    "winners": 0,
                    "casino_spins": 0,
                    "channels": 0,
                    "promocodes": 0,
                    "user_trust_scores": 0,
                    "temporary_admins": 0,
                    "referrals": 1,
                    "user_flags": 1,
                    "admin_audit_log": 1,
                }
                for table, expected in checks.items():
                    async with conn.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
                        self.assertEqual((await cursor.fetchone())[0], expected, table)

                archive_checks = {
                    "contest_reset_user_tickets": 2,
                    "contest_reset_winners": 1,
                    "contest_reset_casino_spins": 1,
                    "contest_reset_channels": 1,
                    "contest_reset_promocodes": 1,
                    "contest_reset_user_trust_scores": 1,
                    "contest_reset_temporary_admins": 1,
                }
                for table, expected in archive_checks.items():
                    async with conn.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE reset_id = ?",
                        (reset_id,),
                    ) as cursor:
                        self.assertEqual((await cursor.fetchone())[0], expected, table)

                runs = await get_contest_reset_runs()
                self.assertEqual(runs[0]["id"], reset_id)
                self.assertEqual(runs[0]["actor_id"], 111)
                self.assertEqual(runs[0]["trust_scores_count"], 1)

                trust_stats = await get_trust_stats()
                self.assertEqual(trust_stats["total"], 0)
            finally:
                await conn.close()
                database_mod._connection = None
                os.unlink(db_path)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
