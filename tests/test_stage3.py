"""
Тесты для Этапа 3: Регистрация и анти-бот фильтры.

Проверяет:
1. Валидация языка (чёрный список).
2. Валидация user ID (порог).
3. Генерация ref_link.
4. Извлечение ref_code из deep link.
5. CRUD: регистрация пользователя + реферал.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

import aiosqlite

# Мок .env для тестов
_TEST_ENV = {
    "BOT_TOKEN": "123456:TEST_TOKEN_FOR_TESTS",
    "ADMIN_IDS": "111,222",
    "END_DATE": "2026-12-31 23:59",
    "MAX_USER_ID": "8000000000",
    "BOT_USERNAME": "TestContestBot",
}
for k, v in _TEST_ENV.items():
    os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database import _SCHEMA_SQL


class TestLanguageValidation(unittest.TestCase):
    """Тесты валидации языка."""

    def test_valid_languages(self) -> None:
        """Допустимые языки проходят проверку."""
        from utils.checks import is_valid_language
        self.assertTrue(is_valid_language("ru"))
        self.assertTrue(is_valid_language("uk"))
        self.assertTrue(is_valid_language("en"))
        self.assertTrue(is_valid_language("de"))
        self.assertTrue(is_valid_language("fr"))
        self.assertTrue(is_valid_language(None))
        self.assertTrue(is_valid_language(""))

    def test_blacklisted_languages(self) -> None:
        """Языки из чёрного списка блокируются."""
        from utils.checks import is_valid_language
        blacklisted = ["ar", "fa", "hi", "ur", "bn", "th", "vi", "zh", "ja", "ko"]
        for lang in blacklisted:
            self.assertFalse(
                is_valid_language(lang),
                f"Язык '{lang}' должен быть заблокирован",
            )

    def test_blacklisted_with_region(self) -> None:
        """Языки с региональным суффиксом тоже блокируются (zh-hans → zh)."""
        from utils.checks import is_valid_language
        self.assertFalse(is_valid_language("zh-hans"))
        self.assertFalse(is_valid_language("zh-TW"))
        self.assertFalse(is_valid_language("ar-SA"))
        self.assertFalse(is_valid_language("ja-JP"))


class TestUserIdValidation(unittest.TestCase):
    """Тесты валидации user ID."""

    def test_valid_user_ids(self) -> None:
        """ID ниже порога проходят."""
        from utils.checks import is_valid_user_id
        self.assertTrue(is_valid_user_id(123456))
        self.assertTrue(is_valid_user_id(746422763))
        self.assertTrue(is_valid_user_id(8000000000))  # ровно порог

    def test_invalid_user_ids(self) -> None:
        """ID выше порога блокируются."""
        from utils.checks import is_valid_user_id
        self.assertFalse(is_valid_user_id(8000000001))
        self.assertFalse(is_valid_user_id(9999999999))


class TestRefLinkGeneration(unittest.TestCase):
    """Тесты генерации реферальных ссылок."""

    def test_ref_link_is_string(self) -> None:
        """ref_link — строка."""
        from handlers.start import _generate_ref_link
        link = _generate_ref_link()
        self.assertIsInstance(link, str)

    def test_ref_link_length(self) -> None:
        """ref_link имеет разумную длину (6 байт → ~8 символов base64)."""
        from handlers.start import _generate_ref_link
        link = _generate_ref_link()
        self.assertGreater(len(link), 4)
        self.assertLess(len(link), 20)

    def test_ref_links_unique(self) -> None:
        """Генерация создаёт уникальные ссылки."""
        from handlers.start import _generate_ref_link
        links = {_generate_ref_link() for _ in range(100)}
        self.assertEqual(len(links), 100, "100 ref_link'ов должны быть уникальными")

    def test_ref_link_url_safe(self) -> None:
        """ref_link содержит только URL-безопасные символы."""
        from handlers.start import _generate_ref_link
        import re
        for _ in range(50):
            link = _generate_ref_link()
            self.assertRegex(
                link, r'^[A-Za-z0-9_-]+$',
                f"ref_link содержит небезопасные символы: '{link}'",
            )


class TestDeepLinkExtraction(unittest.TestCase):
    """Тесты извлечения реферального кода из deep link."""

    def test_valid_ref_link(self) -> None:
        """Корректный deep link ref_xxx."""
        from handlers.start import _extract_ref_link
        self.assertEqual(_extract_ref_link("ref_abc123"), "abc123")
        self.assertEqual(_extract_ref_link("ref_A-b_C"), "A-b_C")

    def test_no_deep_link(self) -> None:
        """Нет deep link → None."""
        from handlers.start import _extract_ref_link
        self.assertIsNone(_extract_ref_link(None))
        self.assertIsNone(_extract_ref_link(""))

    def test_invalid_prefix(self) -> None:
        """Неправильный префикс → None."""
        from handlers.start import _extract_ref_link
        self.assertIsNone(_extract_ref_link("promo_abc"))
        self.assertIsNone(_extract_ref_link("abc123"))
        self.assertIsNone(_extract_ref_link("referral_abc"))


class TestRegistrationFlow(unittest.TestCase):
    """Тесты полного цикла регистрации (БД-уровень)."""

    def setUp(self) -> None:
        self.tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp_file.name
        self.tmp_file.close()

    def tearDown(self) -> None:
        os.unlink(self.db_path)

    def test_registration_and_referral(self) -> None:
        """Полный цикл: регистрация реферера → регистрация реферала → referral запись."""
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
                    create_referral,
                    create_user,
                    get_pending_referral,
                    get_user,
                    get_user_by_ref_link,
                )

                # 1. Регистрируем реферера
                await create_user(
                    user_id=100,
                    username="referrer",
                    first_name="Ref",
                    last_name="Errer",
                    language_code="ru",
                    is_premium=False,
                    ref_link="my_ref_code",
                )

                # 2. Находим реферера по ref_link
                referrer = await get_user_by_ref_link("my_ref_code")
                self.assertIsNotNone(referrer)
                self.assertEqual(referrer["id"], 100)

                # 3. Регистрируем реферала
                await create_user(
                    user_id=200,
                    username="referred",
                    first_name="New",
                    last_name="User",
                    language_code="uk",
                    is_premium=True,
                    ref_link="new_user_ref",
                    ref_by=100,
                )

                # 4. Создаём запись реферала
                await create_referral(referrer_id=100, referred_id=200)

                # 5. Проверяем
                new_user = await get_user(200)
                self.assertEqual(new_user["ref_by"], 100)
                self.assertEqual(new_user["tickets"], 0.0)

                pending = await get_pending_referral(200)
                self.assertIsNotNone(pending)
                self.assertEqual(pending["status"], "pending")

            finally:
                await conn.close()
                database_mod._connection = None

        asyncio.run(_run())

    def test_duplicate_registration_ignored(self) -> None:
        """Повторная регистрация (INSERT OR IGNORE) не создаёт дубликат."""
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

                await create_user(111, "user1", "A", "B", "ru", False, "link1")
                await create_user(111, "user1_dup", "C", "D", "uk", True, "link2")

                user = await get_user(111)
                # Первая запись сохранилась, вторая проигнорирована
                self.assertEqual(user["username"], "user1")
                self.assertEqual(user["language_code"], "ru")

            finally:
                await conn.close()
                database_mod._connection = None

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
