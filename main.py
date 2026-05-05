"""
Contest Giveaway Bot — точка входа.

Запуск бота в режиме long polling с регистрацией
всех роутеров-хендлеров и инициализацией БД.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import NoReturn

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN
from db.database import close_db, init_db
from middlewares.contest_active import ContestActiveMiddleware
from middlewares.localization import LocalizationMiddleware

# ──────────────────── Импорт роутеров ────────────────────
from handlers import (
    admin,
    casino,
    check,
    info,
    language,
    profile,
    promocode,
    referral,
    start,
    winners,
)

# ──────────────────── Логирование ────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def _register_routers(dp: Dispatcher) -> None:
    """Зарегистрировать все роутеры-хендлеры в диспетчере."""
    dp.include_routers(
        admin.router,
        start.router,
        check.router,
        referral.router,
        promocode.router,
        casino.router,
        profile.router,
        info.router,
        language.router,
        winners.router,
    )
    logger.info("Зарегистрировано %d роутеров.", 10)


async def on_startup(bot: Bot) -> None:
    """Действия при запуске бота."""
    logger.info("Инициализация БД...")
    await init_db()
    logger.info("БД готова. Бот запущен!")
    me = await bot.get_me()
    logger.info("Бот: @%s (ID: %d)", me.username, me.id)
    
    # Keep both WebApp entry points on the same active URL.
    from aiogram.types import MenuButtonWebApp, WebAppInfo
    from config import WEBAPP_URL
    from utils.plugins import get_active_plugin_key, get_active_webapp_url
    active_plugin_key = await get_active_plugin_key()
    webapp_url = await get_active_webapp_url()
    logger.info("WEBAPP_URL: %s", WEBAPP_URL)
    logger.info("Active plugin: %s", active_plugin_key)
    logger.info("Active WebApp URL: %s", webapp_url)
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="🎰 Запустить кампанию",
                web_app=WebAppInfo(url=webapp_url),
            )
        )
        logger.info("Default WebApp menu button updated: %s", webapp_url)
    except Exception as e:
        logger.error(f"Failed to set menu button: {e}")


async def on_shutdown(bot: Bot) -> None:
    """Действия при остановке бота."""
    logger.info("Закрытие соединения с БД...")
    await close_db()
    logger.info("Бот остановлен.")


async def main() -> NoReturn:
    """Основная функция запуска бота."""
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher()

    # Регистрация middleware
    dp.message.middleware(LocalizationMiddleware())
    dp.callback_query.middleware(LocalizationMiddleware())
    dp.message.middleware(ContestActiveMiddleware())

    _register_routers(dp)

    # Регистрация lifecycle-хуков
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # API App
    from api.routes import setup_routes
    app = web.Application()
    setup_routes(app)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host='127.0.0.1', port=8080)
    
    logger.info("Запуск polling и API сервера (8080)...")
    await site.start()

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен по Ctrl+C.")
