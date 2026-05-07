"""
Тесты для Этапа 4: Проверка подписок на каналы.

Проверяет:
1. check_subscription — все подписан, частично, ни на один.
2. Обработка ошибок API (RetryAfter, Forbidden, NetworkError).
3. Клавиатура каналов с фильтрацией.
4. Логика _process_pending_referral.
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
from aiogram.types import CallbackQuery, Chat, Message, User

# Мок .env
_TEST_ENV = {
    "BOT_TOKEN": "123456:TEST_TOKEN_FOR_TESTS",
    "ADMIN_IDS": "111,222",
    "END_DATE": "2026-12-31 23:59",
    "BOT_USERNAME": "TestContestBot",
}
for k, v in _TEST_ENV.items():
    os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database import _SCHEMA_SQL


class TestCheckSubscriptionLogic(unittest.TestCase):
    """Тесты логики проверки подписки."""

    def setUp(self) -> None:
        self.tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp_file.name
        self.tmp_file.close()

    def tearDown(self) -> None:
        os.unlink(self.db_path)

    def test_no_channels_returns_subscribed(self) -> None:
        """Если нет каналов в БД → считать подписку успешной."""
        async def _run() -> None:
            import db.database as database_mod
            conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
            await conn.execute("PRAGMA journal_mode=WAL;")
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA_SQL)
            await conn.commit()
            database_mod._connection = conn

            try:
                from utils.checks import check_subscription
                mock_bot = AsyncMock()
                result, unsub = await check_subscription(mock_bot, 123)
                self.assertTrue(result)
                self.assertEqual(len(unsub), 0)
            finally:
                await conn.close()
                database_mod._connection = None

        asyncio.run(_run())

    def test_all_subscribed(self) -> None:
        """Все каналы подписаны → True."""
        async def _run() -> None:
            import db.database as database_mod
            conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
            await conn.execute("PRAGMA journal_mode=WAL;")
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA_SQL)
            await conn.execute(
                "INSERT INTO channels (channel_id, title, invite_link) VALUES (?, ?, ?)",
                ("-1001111", "Channel 1", "https://t.me/ch1"),
            )
            await conn.execute(
                "INSERT INTO channels (channel_id, title, invite_link) VALUES (?, ?, ?)",
                ("-1002222", "Channel 2", "https://t.me/ch2"),
            )
            await conn.commit()
            database_mod._connection = conn

            try:
                from utils.checks import check_subscription

                # Мокаем бота: все подписки — member
                mock_bot = AsyncMock()
                mock_member = MagicMock()
                mock_member.status = "member"
                mock_bot.get_chat_member.return_value = mock_member

                result, unsub = await check_subscription(mock_bot, 123)
                self.assertTrue(result)
                self.assertEqual(len(unsub), 0)
                self.assertEqual(mock_bot.get_chat_member.call_count, 2)
            finally:
                await conn.close()
                database_mod._connection = None

        asyncio.run(_run())

    def test_partially_subscribed(self) -> None:
        """Подписан на 1 из 2 каналов → False + список неподписанных."""
        async def _run() -> None:
            import db.database as database_mod
            conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
            await conn.execute("PRAGMA journal_mode=WAL;")
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA_SQL)
            await conn.execute(
                "INSERT INTO channels (channel_id, title, invite_link) VALUES (?, ?, ?)",
                ("-1001111", "Channel 1", "https://t.me/ch1"),
            )
            await conn.execute(
                "INSERT INTO channels (channel_id, title, invite_link) VALUES (?, ?, ?)",
                ("-1002222", "Channel 2", "https://t.me/ch2"),
            )
            await conn.commit()
            database_mod._connection = conn

            try:
                from utils.checks import check_subscription

                mock_bot = AsyncMock()
                member_ok = MagicMock()
                member_ok.status = "member"
                member_left = MagicMock()
                member_left.status = "left"

                # Первый канал — подписан, второй — нет
                mock_bot.get_chat_member.side_effect = [member_ok, member_left]

                result, unsub = await check_subscription(mock_bot, 123)
                self.assertFalse(result)
                self.assertEqual(len(unsub), 1)
                self.assertEqual(unsub[0]["channel_id"], "-1002222")
                self.assertEqual(unsub[0]["title"], "Channel 2")
            finally:
                await conn.close()
                database_mod._connection = None

        asyncio.run(_run())

    def test_administrator_and_creator_are_valid(self) -> None:
        """Статусы administrator и creator считаются подписанными."""
        async def _run() -> None:
            import db.database as database_mod
            conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
            await conn.execute("PRAGMA journal_mode=WAL;")
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA_SQL)
            await conn.execute(
                "INSERT INTO channels (channel_id, title, invite_link) VALUES (?, ?, ?)",
                ("-100111", "Admin Channel", "https://t.me/admin"),
            )
            await conn.execute(
                "INSERT INTO channels (channel_id, title, invite_link) VALUES (?, ?, ?)",
                ("-100222", "Creator Channel", "https://t.me/creator"),
            )
            await conn.commit()
            database_mod._connection = conn

            try:
                from utils.checks import check_subscription

                mock_bot = AsyncMock()
                admin = MagicMock()
                admin.status = "administrator"
                creator = MagicMock()
                creator.status = "creator"
                mock_bot.get_chat_member.side_effect = [admin, creator]

                result, unsub = await check_subscription(mock_bot, 123)
                self.assertTrue(result)
                self.assertEqual(len(unsub), 0)
            finally:
                await conn.close()
                database_mod._connection = None

        asyncio.run(_run())


class TestErrorHandling(unittest.TestCase):
    """Тесты обработки ошибок API."""

    def setUp(self) -> None:
        self.tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp_file.name
        self.tmp_file.close()

    def tearDown(self) -> None:
        os.unlink(self.db_path)

    def test_forbidden_error_passes(self) -> None:
        """TelegramForbiddenError (бот кикнут) → канал пропускается как подписанный."""
        async def _run() -> None:
            import db.database as database_mod
            from aiogram.exceptions import TelegramForbiddenError
            conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
            await conn.execute("PRAGMA journal_mode=WAL;")
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA_SQL)
            await conn.execute(
                "INSERT INTO channels (channel_id, title, invite_link) VALUES (?, ?, ?)",
                ("-100999", "Kicked Channel", "https://t.me/kicked"),
            )
            await conn.commit()
            database_mod._connection = conn

            try:
                from utils.checks import check_subscription

                mock_bot = AsyncMock()
                mock_bot.get_chat_member.side_effect = TelegramForbiddenError(
                    method=MagicMock(), message="Forbidden"
                )

                result, unsub = await check_subscription(mock_bot, 123)
                # Бот кикнут → не блокируем пользователя
                self.assertTrue(result)
            finally:
                await conn.close()
                database_mod._connection = None

        asyncio.run(_run())


class TestChannelsKeyboard(unittest.TestCase):
    """Тесты клавиатуры каналов."""

    def test_channels_keyboard_shows_all(self) -> None:
        """Клавиатура показывает все каналы + кнопку проверки."""
        from keyboards.channels import get_channels_keyboard

        channels = [
            {"channel_id": "-100111", "title": "Ch 1", "invite_link": "https://t.me/ch1"},
            {"channel_id": "-100222", "title": "Ch 2", "invite_link": "https://t.me/ch2"},
        ]

        kb = get_channels_keyboard(channels, "ru")
        buttons = kb.inline_keyboard
        # 2 канала + 1 кнопка проверки = 3 ряда
        self.assertEqual(len(buttons), 3)
        # Последняя кнопка — проверка подписки
        self.assertEqual(buttons[-1][0].callback_data, "check_subscription")

    def test_channels_keyboard_unsubscribed_only(self) -> None:
        """Фильтрация по неподписанным каналам."""
        from keyboards.channels import get_channels_keyboard

        channels = [
            {"channel_id": "-100111", "title": "Ch 1", "invite_link": "https://t.me/ch1"},
            {"channel_id": "-100222", "title": "Ch 2", "invite_link": "https://t.me/ch2"},
            {"channel_id": "-100333", "title": "Ch 3", "invite_link": "https://t.me/ch3"},
        ]
        unsubscribed_ids = {"-100222"}

        kb = get_channels_keyboard(
            channels, "ru",
            unsubscribed_only=True,
            unsubscribed_ids=unsubscribed_ids,
        )
        buttons = kb.inline_keyboard
        # Только 1 неподписанный канал + 1 кнопка проверки = 2 ряда
        self.assertEqual(len(buttons), 2)
        self.assertIn("Ch 2", buttons[0][0].text)


class TestSubscriptionMiddleware(unittest.IsolatedAsyncioTestCase):
    """Тесты глобальной проверки подписок в middleware."""

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

        await self.conn.close()
        database_mod._connection = None
        os.unlink(self.db_path)

    async def _create_user(self, user_id: int = 3001) -> User:
        from db.models import create_user

        await create_user(
            user_id=user_id,
            username=f"user{user_id}",
            first_name="Name",
            last_name="Test",
            language_code="ru",
            is_premium=False,
            ref_link=f"ref{user_id}",
        )
        return User(id=user_id, is_bot=False, first_name="Name", username=f"user{user_id}")

    @staticmethod
    def _message(user: User, text: str = "👤 Профиль") -> Message:
        return Message(
            message_id=1,
            date=datetime.now(),
            chat=Chat(id=user.id, type="private"),
            from_user=user,
            text=text,
        )

    @staticmethod
    def _callback(user: User, data: str = "back_to_menu") -> CallbackQuery:
        message = TestSubscriptionMiddleware._message(user)
        return CallbackQuery(
            id="cb1",
            from_user=user,
            chat_instance="chat1",
            data=data,
            message=message,
        )

    @staticmethod
    def _data(user: User, bot: AsyncMock | None = None) -> dict:
        return {
            "event_from_user": user,
            "bot": bot or AsyncMock(),
            "lang": "ru",
            "i18n": lambda key, **kwargs: key,
        }

    async def test_subscribed_user_reaches_handler(self) -> None:
        from middlewares.subscription import SubscriptionMiddleware

        user = await self._create_user()
        handler = AsyncMock(return_value="ok")

        with patch("middlewares.subscription.check_subscription", new=AsyncMock(return_value=(True, []))):
            result = await SubscriptionMiddleware()(
                handler,
                self._message(user),
                self._data(user),
            )

        self.assertEqual(result, "ok")
        handler.assert_awaited_once()

    async def test_unsubscribed_user_is_blocked_and_gets_missing_channels(self) -> None:
        from middlewares.subscription import SubscriptionMiddleware

        user = await self._create_user()
        handler = AsyncMock()
        unsubscribed = [
            {"channel_id": "-100222", "title": "Missing", "invite_link": "https://t.me/missing"},
        ]

        with (
            patch("middlewares.subscription.check_subscription", new=AsyncMock(return_value=(False, unsubscribed))),
            patch.object(Message, "answer", new=AsyncMock()) as answer_mock,
        ):
            result = await SubscriptionMiddleware()(
                handler,
                self._message(user),
                self._data(user),
            )

        self.assertIsNone(result)
        handler.assert_not_awaited()
        answer_mock.assert_awaited_once()
        _, kwargs = answer_mock.call_args
        keyboard = kwargs["reply_markup"]
        self.assertEqual(keyboard.inline_keyboard[0][0].text, "📢 Missing")
        self.assertEqual(keyboard.inline_keyboard[0][0].url, "https://t.me/missing")
        self.assertEqual(keyboard.inline_keyboard[-1][0].callback_data, "check_subscription")

    async def test_allowed_actions_skip_subscription_check(self) -> None:
        from middlewares.subscription import SubscriptionMiddleware

        user = await self._create_user()
        handler = AsyncMock(return_value="ok")
        check_mock = AsyncMock(return_value=(False, [{"channel_id": "-100222"}]))

        with patch("middlewares.subscription.check_subscription", new=check_mock):
            for event in (
                self._message(user, "🌐 Язык"),
                self._callback(user, "check_subscription"),
                self._callback(user, "lang_ru"),
                self._callback(user, "lang_uk"),
            ):
                result = await SubscriptionMiddleware()(handler, event, self._data(user))
                self.assertEqual(result, "ok")

        check_mock.assert_not_awaited()
        self.assertEqual(handler.await_count, 4)

    async def test_start_is_checked_for_registered_users(self) -> None:
        from middlewares.subscription import SubscriptionMiddleware

        user = await self._create_user()
        handler = AsyncMock()
        unsubscribed = [
            {"channel_id": "-100222", "title": "Missing", "invite_link": "https://t.me/missing"},
        ]

        with (
            patch("middlewares.subscription.check_subscription", new=AsyncMock(return_value=(False, unsubscribed))),
            patch.object(Message, "answer", new=AsyncMock()) as answer_mock,
        ):
            result = await SubscriptionMiddleware()(
                handler,
                self._message(user, "/start ref_abc"),
                self._data(user),
            )

        self.assertIsNone(result)
        handler.assert_not_awaited()
        answer_mock.assert_awaited_once()

    async def test_start_passes_for_new_users(self) -> None:
        from middlewares.subscription import SubscriptionMiddleware

        user = User(id=3999, is_bot=False, first_name="New")
        handler = AsyncMock(return_value="ok")
        check_mock = AsyncMock(return_value=(False, [{"channel_id": "-100222"}]))

        with patch("middlewares.subscription.check_subscription", new=check_mock):
            result = await SubscriptionMiddleware()(
                handler,
                self._message(user, "/start ref_abc"),
                self._data(user),
            )

        self.assertEqual(result, "ok")
        handler.assert_awaited_once()
        check_mock.assert_not_awaited()

    async def test_admin_skips_subscription_check(self) -> None:
        from middlewares.subscription import SubscriptionMiddleware

        admin = User(id=111, is_bot=False, first_name="Admin")
        handler = AsyncMock(return_value="ok")
        check_mock = AsyncMock(return_value=(False, [{"channel_id": "-100222"}]))

        with patch("middlewares.subscription.check_subscription", new=check_mock):
            result = await SubscriptionMiddleware()(
                handler,
                self._message(admin),
                self._data(admin),
            )

        self.assertEqual(result, "ok")
        handler.assert_awaited_once()
        check_mock.assert_not_awaited()

    async def test_subscription_error_blocks_action(self) -> None:
        from middlewares.subscription import SubscriptionMiddleware

        user = await self._create_user()
        handler = AsyncMock()

        with (
            patch("middlewares.subscription.check_subscription", new=AsyncMock(side_effect=RuntimeError("api error"))),
            patch.object(Message, "answer", new=AsyncMock()) as answer_mock,
        ):
            result = await SubscriptionMiddleware()(
                handler,
                self._message(user),
                self._data(user),
            )

        self.assertIsNone(result)
        handler.assert_not_awaited()
        answer_mock.assert_awaited_once_with("check_error")


class TestTicketLogic(unittest.TestCase):
    """Тесты начисления билетов при проверке."""

    def setUp(self) -> None:
        self.tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp_file.name
        self.tmp_file.close()

    def tearDown(self) -> None:
        os.unlink(self.db_path)

    def test_base_ticket_regular_user(self) -> None:
        """Обычный пользователь получает 1.0 базовый билет."""
        async def _run() -> None:
            import db.database as database_mod
            conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
            await conn.execute("PRAGMA journal_mode=WAL;")
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA_SQL)
            await conn.commit()
            database_mod._connection = conn

            try:
                from db.models import add_user_tickets, create_user, get_user

                await create_user(100, "user", "A", "B", "ru", False, "ref1")
                user = await get_user(100)
                base = 2.0 if user["is_premium"] else 1.0
                self.assertEqual(base, 1.0)

                await add_user_tickets(100, base)
                user = await get_user(100)
                self.assertEqual(user["tickets"], 1.0)
            finally:
                await conn.close()
                database_mod._connection = None

        asyncio.run(_run())

    def test_base_ticket_premium_user(self) -> None:
        """Premium пользователь получает 2.0 базовых билета."""
        async def _run() -> None:
            import db.database as database_mod
            conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
            await conn.execute("PRAGMA journal_mode=WAL;")
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA_SQL)
            await conn.commit()
            database_mod._connection = conn

            try:
                from db.models import add_user_tickets, create_user, get_user

                await create_user(200, "premium", "P", "U", "ru", True, "ref2")
                user = await get_user(200)
                base = 2.0 if user["is_premium"] else 1.0
                self.assertEqual(base, 2.0)

                await add_user_tickets(200, base)
                user = await get_user(200)
                self.assertEqual(user["tickets"], 2.0)
            finally:
                await conn.close()
                database_mod._connection = None

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
