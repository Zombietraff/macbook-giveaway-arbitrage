"""
Тесты для Этапа 11: модуль «Казик».
"""

from __future__ import annotations

import asyncio
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
