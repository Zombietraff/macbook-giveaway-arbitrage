"""
Обработчик промокодов (пасхалок).

FSM-состояние для ввода кода:
1. Кнопка «Нашёл пасхалку» → запрос ввода кода.
2. Ввод кода → валидация, проверка подписки, активация.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from db.models import activate_promocode, add_user_tickets, get_promocode, get_user
from keyboards.main_menu import get_cancel_keyboard, get_main_menu_keyboard
from utils.checks import check_subscription

logger = logging.getLogger(__name__)
router = Router(name="promocode")


class PromoCodeInput(StatesGroup):
    """FSM-состояния для ввода промокода."""
    waiting_for_code = State()


@router.message(F.text.in_({"🥚 Нашёл пасхалку", "🥚 Знайшов пасхалку"}))
async def ask_for_code(
    message: Message,
    state: FSMContext,
    i18n: Callable,
    lang: str,
    **kwargs: Any,
) -> None:
    """Запросить ввод промокода."""
    user_id = message.from_user.id
    db_user = await get_user(user_id)

    if not db_user:
        await message.answer(i18n("start"))
        return

    await state.set_state(PromoCodeInput.waiting_for_code)
    await message.answer(
        i18n("promo_enter"),
        reply_markup=get_cancel_keyboard(lang),
    )

    logger.info("User %d начал ввод промокода", user_id)


@router.message(PromoCodeInput.waiting_for_code, F.text.in_({"❌ Отмена", "❌ Скасувати"}))
async def cancel_promo_input(
    message: Message,
    state: FSMContext,
    i18n: Callable,
    lang: str,
    **kwargs: Any,
) -> None:
    """Отмена ввода промокода."""
    await state.clear()
    await message.answer(
        i18n("promo_cancel"),
        reply_markup=get_main_menu_keyboard(lang),
    )


@router.message(PromoCodeInput.waiting_for_code)
async def process_promo_code(
    message: Message,
    bot: Bot,
    state: FSMContext,
    i18n: Callable,
    lang: str,
    **kwargs: Any,
) -> None:
    """Обработка введённого промокода."""
    user_id = message.from_user.id
    code = message.text.strip()

    logger.info("User %d вводит промокод: '%s'", user_id, code)

    # 1. Проверяем код в БД
    promo = await get_promocode(code)
    if not promo or promo["used_by"] is not None:
        await message.answer(i18n("promo_invalid"))
        await state.clear()
        await message.answer(
            i18n("menu_back"),
            reply_markup=get_main_menu_keyboard(lang),
        )
        return

    # 2. Проверяем подписку пользователя
    try:
        all_subscribed, _ = await check_subscription(bot, user_id)
    except Exception as e:
        logger.error("Ошибка проверки подписки при активации промо user=%d: %s", user_id, e)
        await message.answer(i18n("check_error"))
        await state.clear()
        return

    if not all_subscribed:
        await message.answer(i18n("promo_not_subscribed"))
        await state.clear()
        await message.answer(
            i18n("menu_back"),
            reply_markup=get_main_menu_keyboard(lang),
        )
        return

    # 3. Активируем промокод
    await activate_promocode(code, user_id)
    await add_user_tickets(user_id, 5.0)

    # Получаем обновлённый баланс
    db_user = await get_user(user_id)
    total = db_user["tickets"] if db_user else 5.0

    await state.clear()
    await message.answer(
        i18n("promo_success", total=int(total)),
        reply_markup=get_main_menu_keyboard(lang),
    )

    logger.info(
        "Промокод '%s' активирован user=%d, +5 билетов (всего: %.1f)",
        code, user_id, total,
    )
