"""
Тесты для Этапа 2: Система локализации.

Проверяет:
1. Корректность загрузки и полноту файлов локалей.
2. Функцию get_text() с подстановкой и фоллбэком.
3. Определение языка по Telegram language_code.
4. Клавиатуры с разными языками.
5. Консистентность ключей между языками.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

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


class TestLocaleFiles(unittest.TestCase):
    """Тесты файлов локализации."""

    def setUp(self) -> None:
        from config import LOCALES_DIR
        self.locales_dir = LOCALES_DIR

    def test_ru_json_exists_and_valid(self) -> None:
        """ru.json существует и содержит валидный JSON."""
        path = self.locales_dir / "ru.json"
        self.assertTrue(path.exists())
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)
        self.assertGreater(len(data), 20, "ru.json должен содержать >= 20 ключей")

    def test_uk_json_exists_and_valid(self) -> None:
        """uk.json существует и содержит валидный JSON."""
        path = self.locales_dir / "uk.json"
        self.assertTrue(path.exists())
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)
        self.assertGreater(len(data), 20, "uk.json должен содержать >= 20 ключей")

    def test_keys_consistency(self) -> None:
        """Оба файла локалей содержат одинаковый набор ключей."""
        ru_path = self.locales_dir / "ru.json"
        uk_path = self.locales_dir / "uk.json"

        with open(ru_path, "r", encoding="utf-8") as f:
            ru_keys = set(json.load(f).keys())
        with open(uk_path, "r", encoding="utf-8") as f:
            uk_keys = set(json.load(f).keys())

        missing_in_uk = ru_keys - uk_keys
        missing_in_ru = uk_keys - ru_keys

        self.assertEqual(
            missing_in_uk, set(),
            f"Ключи есть в ru.json, но отсутствуют в uk.json: {missing_in_uk}",
        )
        self.assertEqual(
            missing_in_ru, set(),
            f"Ключи есть в uk.json, но отсутствуют в ru.json: {missing_in_ru}",
        )

    def test_required_keys_present(self) -> None:
        """Все обязательные ключи присутствуют в обоих файлах."""
        required_keys = {
            "start", "not_subscribed", "check_success",
            "referral_invite", "promo_enter", "promo_success",
            "profile_title", "info_title", "info_text",
            "lang_current", "lang_changed", "lang_name",
            "menu_check", "menu_invite", "menu_promo",
            "menu_info", "menu_profile", "menu_language",
            "menu_back", "menu_cancel",
            "btn_check_subscription",
        }

        for lang in ("ru", "uk"):
            path = self.locales_dir / f"{lang}.json"
            with open(path, "r", encoding="utf-8") as f:
                keys = set(json.load(f).keys())

            missing = required_keys - keys
            self.assertEqual(
                missing, set(),
                f"В {lang}.json отсутствуют обязательные ключи: {missing}",
            )


class TestGetText(unittest.TestCase):
    """Тесты функции get_text()."""

    def test_basic_text_ru(self) -> None:
        """Получение текста на русском."""
        from middlewares.localization import get_text
        text = get_text("lang_name", "ru")
        self.assertIn("Русский", text)

    def test_basic_text_uk(self) -> None:
        """Получение текста на украинском."""
        from middlewares.localization import get_text
        text = get_text("lang_name", "uk")
        self.assertIn("Українська", text)

    def test_format_substitution(self) -> None:
        """Подстановка параметров в текст."""
        from middlewares.localization import get_text
        text = get_text("check_success", "ru", tickets=3.5)
        self.assertIn("3.5", text)

    def test_missing_key_returns_warning(self) -> None:
        """Несуществующий ключ возвращает строку с предупреждением."""
        from middlewares.localization import get_text
        text = get_text("nonexistent_key_xyz", "ru")
        self.assertIn("⚠️", text)
        self.assertIn("nonexistent_key_xyz", text)

    def test_fallback_to_russian(self) -> None:
        """Неизвестный язык фоллбэчит на русский."""
        from middlewares.localization import get_text
        text_unknown = get_text("lang_name", "fr")
        text_ru = get_text("lang_name", "ru")
        self.assertEqual(text_unknown, text_ru)

    def test_different_languages_different_text(self) -> None:
        """Тексты на разных языках отличаются."""
        from middlewares.localization import get_text
        ru = get_text("start", "ru")
        uk = get_text("start", "uk")
        self.assertNotEqual(ru, uk)


class TestDetectLanguage(unittest.TestCase):
    """Тесты определения языка."""

    def test_uk_language(self) -> None:
        """Украинский язык определяется корректно."""
        from middlewares.localization import detect_language
        self.assertEqual(detect_language("uk"), "uk")
        self.assertEqual(detect_language("uk-UA"), "uk")

    def test_ru_language(self) -> None:
        """Русский и все остальные → русский."""
        from middlewares.localization import detect_language
        self.assertEqual(detect_language("ru"), "ru")
        self.assertEqual(detect_language("en"), "ru")
        self.assertEqual(detect_language("de"), "ru")
        self.assertEqual(detect_language(None), "ru")


class TestKeyboards(unittest.TestCase):
    """Тесты клавиатур с локализацией."""

    def test_main_menu_ru(self) -> None:
        """Главное меню на русском содержит правильные кнопки."""
        from keyboards.main_menu import get_main_menu_keyboard
        kb = get_main_menu_keyboard("ru")
        all_texts = [btn.text for row in kb.keyboard for btn in row]
        self.assertIn("👥 Пригласить друга", all_texts)
        self.assertIn("👤 Профиль", all_texts)
        self.assertIn("🌐 Язык", all_texts)

    def test_main_menu_uk(self) -> None:
        """Главное меню на украинском содержит правильные кнопки."""
        from keyboards.main_menu import get_main_menu_keyboard
        kb = get_main_menu_keyboard("uk")
        all_texts = [btn.text for row in kb.keyboard for btn in row]
        self.assertIn("👥 Запросити друга", all_texts)
        self.assertIn("👤 Профіль", all_texts)
        self.assertIn("🌐 Мова", all_texts)

    def test_language_keyboard(self) -> None:
        """Клавиатура выбора языка содержит обе опции."""
        from keyboards.main_menu import get_language_keyboard
        kb = get_language_keyboard()
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertIn("🇷🇺 Русский", texts)
        self.assertIn("🇺🇦 Українська", texts)

    def test_main_menu_different_languages(self) -> None:
        """Клавиатуры RU и UK содержат разные тексты."""
        from keyboards.main_menu import get_main_menu_keyboard
        ru_texts = [btn.text for row in get_main_menu_keyboard("ru").keyboard for btn in row]
        uk_texts = [btn.text for row in get_main_menu_keyboard("uk").keyboard for btn in row]
        self.assertNotEqual(ru_texts, uk_texts)


if __name__ == "__main__":
    unittest.main()
