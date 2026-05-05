"""
Тесты для Этапа 11: модуль «Казик».
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiosqlite
import config

# Мок .env
_TEST_ENV = {
    "BOT_TOKEN": "123456:TEST_TOKEN_FOR_TESTS",
    "ADMIN_IDS": "111,222",
    "BOT_USERNAME": "TestContestBot",
}
for k, v in _TEST_ENV.items():
    os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database import _SCHEMA_SQL


class _FakeWebAppRequest(dict):
    def __init__(self, body: dict) -> None:
        super().__init__()
        self.headers = {"Authorization": "tma TEST_INIT_DATA"}
        self.query = {}
        self._body = body

    async def json(self) -> dict:
        return self._body


class TestCasinoStage11(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp_file.name
        self.tmp_file.close()

        import db.database as database_mod

        self.conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
        await self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(_SCHEMA_SQL)
        await self.conn.commit()
        database_mod._connection = self.conn

    async def asyncTearDown(self) -> None:
        import db.database as database_mod
        from handlers.casino import _spinning_users

        _spinning_users.clear()
        await self.conn.close()
        database_mod._connection = None
        os.unlink(self.db_path)

    async def _create_user_with_tickets(self, user_id: int, tickets: float, lang: str = "ru") -> None:
        from db.models import create_user, update_user_tickets

        await create_user(user_id, f"user{user_id}", "Name", "Test", lang, False, f"ref{user_id}")
        await update_user_tickets(user_id, tickets)

    async def test_balance_1_button_visible_and_click_returns_min_balance(self) -> None:
        """Баланс 1: кнопка видна в меню, вход в казик отклоняется min_balance."""
        from handlers.casino import start_casino
        from keyboards.main_menu import get_main_menu_keyboard
        from middlewares.localization import get_text

        await self._create_user_with_tickets(1001, 1.0)

        keyboard = get_main_menu_keyboard("ru")
        all_texts = [button.text for row in keyboard.keyboard for button in row]
        self.assertIn(get_text("menu_casino", "ru"), all_texts)

        message = SimpleNamespace(
            from_user=SimpleNamespace(id=1001),
            chat=SimpleNamespace(id=1001),
            answer=AsyncMock(),
        )
        state = AsyncMock()
        bot = AsyncMock()

        with patch("handlers.casino.check_subscription", new=AsyncMock(return_value=(True, []))):
            await start_casino(
                message=message,
                bot=bot,
                state=state,
                i18n=lambda key, **kwargs: key,
                lang="ru",
            )

        message.answer.assert_awaited_with("casino_min_balance")

    async def test_balance_2_only_bet_1_and_loss_leaves_1_ticket(self) -> None:
        """Баланс 2: доступна только ставка 1, при лузе баланс становится 1."""
        from db.models import get_user, play_casino_spin_atomic
        from handlers.casino import _available_bets

        await self._create_user_with_tickets(1002, 2.0)

        self.assertEqual(_available_bets(2.0), [1])

        spin_result = await play_casino_spin_atomic(
            user_id=1002,
            bet_amount=1.0,
            dice_value=10,
            result_type="loss",
            multiplier=0.0,
        )

        self.assertEqual(spin_result["result_type"], "loss")
        self.assertEqual(spin_result["balance_after"], 1.0)

        db_user = await get_user(1002)
        self.assertEqual(db_user["tickets"], 1.0)

    async def test_webapp_spin_rejects_spending_last_ticket(self) -> None:
        """WebApp spin не может списать последний билет."""
        from api.routes import spin_slot
        from db.models import get_user, set_user_flag

        await self._create_user_with_tickets(1012, 1.0)
        await set_user_flag(1012, "webapp_disclaimer_accepted")

        request = _FakeWebAppRequest({"bet": 1})

        with patch("api.routes.validate_init_data", return_value={"id": 1012}):
            response = await spin_slot(request)

        self.assertEqual(response.status, 400)
        self.assertIn("Insufficient balance", json.loads(response.text)["error"])

        db_user = await get_user(1012)
        self.assertEqual(db_user["tickets"], 1.0)

        async with self.conn.execute("SELECT COUNT(*) FROM casino_spins WHERE user_id = ?", (1012,)) as cursor:
            self.assertEqual((await cursor.fetchone())[0], 0)

    async def test_webapp_spin_balance_2_bet_1_loss_leaves_1_ticket(self) -> None:
        """WebApp spin при balance=2 и bet=1 может проиграть только до 1 билета."""
        from api.routes import spin_slot
        from db.models import get_user, set_user_flag

        await self._create_user_with_tickets(1013, 2.0)
        await set_user_flag(1013, "webapp_disclaimer_accepted")

        request = _FakeWebAppRequest({"bet": 1})

        with (
            patch("api.routes.validate_init_data", return_value={"id": 1013}),
            patch("api.routes.generate_spin_result", return_value=["CHERRY", "APPLE", "BANANA"]),
        ):
            response = await spin_slot(request)

        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.text)["coins"], 1.0)

        db_user = await get_user(1013)
        self.assertEqual(db_user["tickets"], 1.0)

    async def test_webapp_spin_balance_2_bet_2_is_rejected(self) -> None:
        """WebApp spin отклоняет ставку, которая оставила бы 0 билетов."""
        from api.routes import spin_slot
        from db.models import get_user, set_user_flag

        await self._create_user_with_tickets(1014, 2.0)
        await set_user_flag(1014, "webapp_disclaimer_accepted")

        request = _FakeWebAppRequest({"bet": 2})

        with patch("api.routes.validate_init_data", return_value={"id": 1014}):
            response = await spin_slot(request)

        self.assertEqual(response.status, 400)

        db_user = await get_user(1014)
        self.assertEqual(db_user["tickets"], 2.0)

    async def test_webapp_launch_token_auth_fallback_accepts_disclaimer(self) -> None:
        """Signed launch-token fallback авторизует WebApp API без Telegram initData."""
        from api.routes import accept_disclaimer
        from db.models import has_user_flag
        from utils.webapp_launch import create_webapp_launch_token

        await self._create_user_with_tickets(1017, 1.0)

        request = _FakeWebAppRequest({})
        request.headers = {
            "Authorization": "tma ",
            "X-WebApp-Launch-Token": create_webapp_launch_token(1017),
        }

        response = await accept_disclaimer(request)

        self.assertEqual(response.status, 200)
        self.assertTrue(await has_user_flag(1017, "webapp_disclaimer_accepted"))

    async def test_repeat_subscription_check_with_last_check_does_not_reissue_tickets(self) -> None:
        """Если last_check_at уже выставлен, повторная проверка не начисляет стартовые билеты даже при 0."""
        from db.models import get_user, update_last_check
        from handlers.check import check_subscription_handler

        await self._create_user_with_tickets(1015, 0.0)
        await update_last_check(1015)

        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=1015, username="user1015"),
            answer=AsyncMock(),
            message=SimpleNamespace(answer=AsyncMock()),
        )

        with (
            patch("handlers.check.check_subscription", new=AsyncMock(return_value=(True, []))),
            patch("handlers.check.refresh_user_trust_score", new=AsyncMock()),
        ):
            await check_subscription_handler(
                callback=callback,
                bot=AsyncMock(),
                i18n=lambda key, **kwargs: key,
                lang="ru",
            )

        db_user = await get_user(1015)
        self.assertEqual(db_user["tickets"], 0.0)
        callback.message.answer.assert_awaited()

    async def test_reset_clears_last_check_and_allows_initial_tickets_again(self) -> None:
        """После reset last_check_at=NULL, поэтому новый конкурс снова выдаёт стартовый билет."""
        from db.models import get_user, reset_contest_with_archive, update_last_check
        from handlers.check import check_subscription_handler

        await self._create_user_with_tickets(1016, 3.0)
        await update_last_check(1016)
        await reset_contest_with_archive(actor_id=111)

        db_user = await get_user(1016)
        self.assertEqual(db_user["tickets"], 0.0)
        self.assertIsNone(db_user["last_check_at"])

        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=1016, username="user1016"),
            answer=AsyncMock(),
            message=SimpleNamespace(answer=AsyncMock()),
        )

        with (
            patch("handlers.check.check_subscription", new=AsyncMock(return_value=(True, []))),
            patch("handlers.check.refresh_user_trust_score", new=AsyncMock()),
            patch("handlers.check._process_pending_referral", new=AsyncMock()),
        ):
            await check_subscription_handler(
                callback=callback,
                bot=AsyncMock(),
                i18n=lambda key, **kwargs: key,
                lang="ru",
            )

        db_user = await get_user(1016)
        self.assertEqual(db_user["tickets"], 1.0)
        self.assertIsNotNone(db_user["last_check_at"])

    async def test_daily_limit_blocks_fourth_spin(self) -> None:
        """После достижения дневного лимита вход блокируется по daily_limit."""
        from handlers.casino import _validate_casino_entry

        await self._create_user_with_tickets(1003, 10.0)

        await self.conn.executemany(
            """
            INSERT INTO casino_spins (
                user_id, bet_amount, dice_value, result_type, multiplier, balance_before, balance_after
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1003, 1.0, 5, "loss", 0.0, 10.0, 9.0)
                for _ in range(config.CASINO_DAILY_LIMIT)
            ],
        )
        await self.conn.commit()

        with patch("handlers.casino.check_subscription", new=AsyncMock(return_value=(True, []))):
            is_valid, reason, _ = await _validate_casino_entry(
                bot=AsyncMock(),
                user_id=1003,
                balance=13.0,
                i18n=lambda key, **kwargs: key,
            )

        self.assertFalse(is_valid)
        self.assertEqual(reason, "casino_daily_limit")

    async def test_jackpot_value_64_updates_balance_with_plus_bet_x3(self) -> None:
        """dice.value == 64: статус jackpot, net profit = +bet*4 при x5 выплате."""
        from db.models import get_user, play_casino_spin_atomic

        await self._create_user_with_tickets(1004, 5.0)

        spin_result = await play_casino_spin_atomic(
            user_id=1004,
            bet_amount=2.0,
            dice_value=64,
            result_type="jackpot",
            multiplier=5.0,
        )

        self.assertEqual(spin_result["result_type"], "jackpot")
        self.assertEqual(spin_result["net_profit"], 8.0)  # + bet * 4
        self.assertEqual(spin_result["balance_after"], 13.0)

        db_user = await get_user(1004)
        self.assertEqual(db_user["tickets"], 13.0)

    async def test_only_three_equal_symbols_are_win(self) -> None:
        """7-7-🍋 (48) не считается win; win только за три одинаковых, 7-7-7 это jackpot."""
        from handlers.casino import _map_result

        self.assertEqual(_map_result(48), ("loss", 0.0))
        self.assertEqual(_map_result(1), ("win", 3.0))
        self.assertEqual(_map_result(22), ("win", 3.0))
        self.assertEqual(_map_result(43), ("win", 3.0))
        self.assertEqual(_map_result(64), ("jackpot", 5.0))

    async def test_second_parallel_click_is_ignored(self) -> None:
        """Одновременные клики: второй игнорируется, транзакция остаётся консистентной."""
        from handlers.casino import CasinoStates, process_casino_bet

        await self._create_user_with_tickets(1005, 5.0)

        started = asyncio.Event()
        release = asyncio.Event()

        async def _send_dice_side_effect(*args, **kwargs):
            started.set()
            await release.wait()
            return SimpleNamespace(dice=SimpleNamespace(value=50))

        bot = AsyncMock()
        bot.send_dice = AsyncMock(side_effect=_send_dice_side_effect)

        callback_message_1 = SimpleNamespace(
            chat=SimpleNamespace(id=1005),
            answer=AsyncMock(),
            edit_reply_markup=AsyncMock(),
        )
        callback1 = SimpleNamespace(
            from_user=SimpleNamespace(id=1005),
            data="casino_bet_1",
            answer=AsyncMock(),
            message=callback_message_1,
        )

        callback_message_2 = SimpleNamespace(
            chat=SimpleNamespace(id=1005),
            answer=AsyncMock(),
            edit_reply_markup=AsyncMock(),
        )
        callback2 = SimpleNamespace(
            from_user=SimpleNamespace(id=1005),
            data="casino_bet_1",
            answer=AsyncMock(),
            message=callback_message_2,
        )

        state1 = AsyncMock()
        state1.get_state = AsyncMock(return_value=CasinoStates.waiting_for_bet.state)
        state2 = AsyncMock()
        state2.get_state = AsyncMock(return_value=CasinoStates.waiting_for_bet.state)

        with patch("handlers.casino.check_subscription", new=AsyncMock(return_value=(True, []))):
            task1 = asyncio.create_task(
                process_casino_bet(
                    callback=callback1,
                    bot=bot,
                    state=state1,
                    i18n=lambda key, **kwargs: key,
                    lang="ru",
                )
            )

            await started.wait()

            await process_casino_bet(
                callback=callback2,
                bot=bot,
                state=state2,
                i18n=lambda key, **kwargs: key,
                lang="ru",
            )

            release.set()
            await task1

        callback2.answer.assert_awaited_with("casino_busy", show_alert=True)

        async with self.conn.execute("SELECT COUNT(*) FROM casino_spins WHERE user_id = ?", (1005,)) as cursor:
            spins_count = (await cursor.fetchone())[0]

        self.assertEqual(spins_count, 1)

    async def test_ru_uk_locales_switch_for_casino_texts(self) -> None:
        """RU/UK локали для казино переключаются корректно."""
        from middlewares.localization import get_text

        ru_win = get_text("casino_win", "ru", net_profit=1)
        uk_win = get_text("casino_win", "uk", net_profit=1)

        ru_cancel = get_text("menu_cancel", "ru")
        uk_cancel = get_text("menu_cancel", "uk")

        self.assertNotEqual(ru_win, uk_win)
        self.assertNotEqual(ru_cancel, uk_cancel)


if __name__ == "__main__":
    unittest.main()
