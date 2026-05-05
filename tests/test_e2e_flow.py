"""
End-to-End тестирование основной логики бота Contest Giveaway.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite

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

class TestE2EFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp_file.name
        self.tmp_file.close()

        import db.database as database_mod
        self.conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
        await self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(_SCHEMA_SQL)
        
        # Добавляем каналы
        await self.conn.execute(
            "INSERT INTO channels (channel_id, title, invite_link) VALUES (?, ?, ?)",
            ("-1001", "Ch1", "link1"),
        )
        await self.conn.commit()
        database_mod._connection = self.conn

    async def asyncTearDown(self) -> None:
        import db.database as database_mod
        await self.conn.close()
        database_mod._connection = None
        os.unlink(self.db_path)

    @patch('aiogram.types.Message.answer', new_callable=AsyncMock)
    @patch('aiogram.types.CallbackQuery.answer', new_callable=AsyncMock)
    async def test_full_user_journey(self, mock_cb_answer, mock_msg_answer) -> None:
        """
        Полный цикл: 
        1. User A (Premium) -> /start -> check -> 2.0 tickets
        2. User B (Normal) -> /start (ref of A) -> check -> 1.0 ticket + 1.0 to A
        3. User B -> uses Promocode -> +5.0 tickets
        4. Draw -> verification
        """
        from handlers.start import cmd_start
        from handlers.check import check_subscription_handler
        from handlers.promocode import PromoCodeInput, process_promo_code
        from db.models import get_user, add_promocode, get_all_winners, set_end_date, set_contest_prizes

        # Ставим дату будущего для корректной работы middleware
        await set_end_date(datetime(2026, 12, 31, 23, 59))
        await set_contest_prizes([(2, "Prize A"), (1, "Prize B"), (1, "Prize C")], created_by=111)
        from utils.draw import perform_draw
        from aiogram.types import Message, User, CallbackQuery, Chat
        from aiogram.fsm.context import FSMContext

        mock_bot = AsyncMock()
        mock_member = MagicMock()
        mock_member.status = "member"
        mock_bot.get_chat_member.return_value = mock_member
        
        # --- User A (Premium) ---
        user_a = User(id=111, is_bot=False, first_name="A", username="user_a", language_code="ru", is_premium=True)
        msg_a = Message(message_id=1, date=datetime.now(), chat=Chat(id=111, type="private"), from_user=user_a, text="/start")
        
        mock_command_a = MagicMock()
        mock_command_a.args = None
        
        mock_i18n = lambda k, **kw: k
        
        # 1. Start User A
        await cmd_start(message=msg_a, command=mock_command_a, i18n=mock_i18n, lang="ru")
        
        db_user_a = await get_user(111)
        self.assertIsNotNone(db_user_a)
        self.assertEqual(db_user_a["tickets"], 0.0)
        
        ref_link_a = db_user_a["ref_link"]
        
        # 2. Check Subscription User A
        cb_a = CallbackQuery(id="1", from_user=user_a, chat_instance="1", data="check_subscription", message=msg_a)
        await check_subscription_handler(callback=cb_a, bot=mock_bot, i18n=mock_i18n, lang="ru")
        
        db_user_a = await get_user(111)
        self.assertEqual(db_user_a["tickets"], 2.0)
        
        # --- User B (Normal) ---
        user_b = User(id=222, is_bot=False, first_name="B", username="user_b", language_code="ru", is_premium=False)
        msg_b = Message(message_id=2, date=datetime.now(), chat=Chat(id=222, type="private"), from_user=user_b, text=f"/start ref_{ref_link_a}")
        
        mock_command_b = MagicMock()
        mock_command_b.args = f"ref_{ref_link_a}"
        
        # 1. Start User B with Ref
        await cmd_start(message=msg_b, command=mock_command_b, i18n=mock_i18n, lang="ru")
        
        db_user_b = await get_user(222)
        self.assertEqual(db_user_b["ref_by"], 111)
        self.assertEqual(db_user_b["tickets"], 0.0)
        
        # 2. Check Subscription User B (triggers Ref bonus for A)
        cb_b = CallbackQuery(id="2", from_user=user_b, chat_instance="2", data="check_subscription", message=msg_b)
        await check_subscription_handler(callback=cb_b, bot=mock_bot, i18n=mock_i18n, lang="ru")
        
        db_user_b = await get_user(222)
        self.assertEqual(db_user_b["tickets"], 1.0)
        
        db_user_a = await get_user(111)
        self.assertEqual(db_user_a["tickets"], 3.0)  # 2.0 + 1.0 from ref
        
        # --- Promocode ---
        await add_promocode("E2E_PROMO")
        
        mock_state = AsyncMock(spec=FSMContext)
        msg_promo = Message(message_id=3, date=datetime.now(), chat=Chat(id=222, type="private"), from_user=user_b, text="E2E_PROMO")
        
        await process_promo_code(message=msg_promo, bot=mock_bot, state=mock_state, i18n=mock_i18n, lang="ru")
        
        db_user_b = await get_user(222)
        self.assertEqual(db_user_b["tickets"], 6.0) # 1.0 + 5.0
        
        # --- Draw ---
        # Add 2 more users to reach minimum 4 participants for draw
        from db.models import create_user, add_user_tickets
        await create_user(333, "user_c", "C", "", "ru", False, "ref_c")
        await add_user_tickets(333, 1.0)
        await create_user(444, "user_d", "D", "", "ru", False, "ref_d")
        await add_user_tickets(444, 1.0)
        
        winners = await perform_draw(bot=mock_bot)
        
        self.assertEqual(len(winners), 4) # We must have exactly 4 winners
        
        db_winners = await get_all_winners()
        self.assertEqual(len(db_winners), 4)
        
        prizes = [w["prize"] for w in db_winners]
        self.assertEqual(prizes, ["Prize A", "Prize A", "Prize B", "Prize C"])

if __name__ == "__main__":
    unittest.main()
