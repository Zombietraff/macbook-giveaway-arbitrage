"""
Обработчик кнопки «Проверить подписку».

Логика:
1. Вызов check_subscription() для всех каналов.
2. Если не все подписки — сообщение + список неподписанных каналов.
3. Если все подписки — сообщение «Успех!» (начисление билетов → Этап 5).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from db.models import get_all_channels, get_user
from keyboards.channels import get_channels_keyboard
from utils.checks import check_subscription
from utils.userbot_trust import refresh_user_trust_score

logger = logging.getLogger(__name__)
router = Router(name="check")


@router.callback_query(F.data == "check_subscription")
async def check_subscription_handler(
    callback: CallbackQuery,
    bot: Bot,
    i18n: Callable,
    lang: str,
    **kwargs: Any,
) -> None:
    """Обработка нажатия кнопки «Проверить подписку»."""
    user_id = callback.from_user.id

    logger.info("Проверка подписки для user=%d", user_id)
    await callback.answer()

    # Проверяем, зарегистрирован ли пользователь
    db_user = await get_user(user_id)
    if not db_user:
        await callback.message.answer(i18n("start"))
        return

    # Проверяем подписки
    try:
        all_subscribed, unsubscribed = await check_subscription(bot, user_id)
    except Exception as e:
        logger.error("Ошибка проверки подписки user=%d: %s", user_id, e)
        await callback.message.answer(i18n("check_error"))
        return

    if not all_subscribed:
        # Показываем неподписанные каналы
        channels = await get_all_channels()
        unsubscribed_ids = {ch["channel_id"] for ch in unsubscribed}

        await callback.message.answer(
            i18n("not_subscribed"),
            reply_markup=get_channels_keyboard(
                channels,
                lang=lang,
                unsubscribed_only=True,
                unsubscribed_ids=unsubscribed_ids,
            ),
        )
        logger.info(
            "User %d не подписан на %d каналов: %s",
            user_id,
            len(unsubscribed),
            [ch["title"] for ch in unsubscribed],
        )
        return

    # ──────────────────── Все подписки пройдены ────────────────────
    tickets = float(db_user["tickets"] or 0.0)
    has_received_initial_tickets = db_user["last_check_at"] is not None
    await refresh_user_trust_score(
        user_id=user_id,
        username=callback.from_user.username or db_user["username"],
    )

    if has_received_initial_tickets:
        # Повторная проверка — просто обновляем last_check_at
        from db.models import update_last_check
        from keyboards.main_menu import get_active_main_menu_keyboard
        await update_last_check(user_id)
        await callback.message.answer(
            i18n("check_already", tickets=int(tickets)),
            reply_markup=await get_active_main_menu_keyboard(lang),
        )
        logger.info("Повторная проверка user=%d, tickets=%.1f", user_id, tickets)
    else:
        # Первая успешная проверка — начисление билетов (Этап 5)
        # Пока заглушка: сообщение об успехе
        base_tickets = 2.0 if db_user["is_premium"] else 1.0

        from db.models import add_user_tickets, update_last_check
        await add_user_tickets(user_id, base_tickets)
        await update_last_check(user_id)

        # Обработка реферала (если есть pending)
        await _process_pending_referral(bot, user_id, i18n, lang)

        # Показываем успех + главное меню
        from keyboards.main_menu import get_active_main_menu_keyboard
        await callback.message.answer(
            i18n("check_success", tickets=int(base_tickets)),
            reply_markup=await get_active_main_menu_keyboard(lang),
        )
        logger.info(
            "Первая проверка user=%d: начислено %.1f билетов (premium=%s)",
            user_id, base_tickets, db_user["is_premium"],
        )


async def _process_pending_referral(
    bot: Bot,
    referred_id: int,
    i18n: Callable,
    lang: str,
) -> None:
    """
    Обработать ожидающий реферал после успешной проверки подписки.

    Если у пользователя есть pending-реферал:
    - Обновить статус на 'completed'
    - Начислить рефереру +1 билет
    - Отправить уведомление рефереру
    """
    from db.models import (
        add_user_tickets,
        get_pending_referral,
        get_user,
        update_referral_status,
    )
    from utils.notifications import notify_referrer

    pending = await get_pending_referral(referred_id)
    if not pending:
        return

    referrer_id = pending["referrer_id"]

    # Обновляем статус реферала
    await update_referral_status(referrer_id, referred_id, "completed")

    # Начисляем рефереру +1 билет
    await add_user_tickets(referrer_id, 1.0)

    # Получаем данные для уведомления
    referred_user = await get_user(referred_id)
    referrer_user = await get_user(referrer_id)

    referred_username = (
        referred_user["username"]
        or referred_user["first_name"]
        or str(referred_id)
    ) if referred_user else str(referred_id)

    referrer_total = referrer_user["tickets"] if referrer_user else 0

    # Уведомляем реферера
    await notify_referrer(
        bot=bot,
        referrer_id=referrer_id,
        referred_username=referred_username,
        referrer_total_tickets=referrer_total,
        lang=referrer_user["language_code"] if referrer_user else "ru",
    )

    logger.info(
        "Реферал завершён: %d → %d, рефереру начислен +1 билет (всего: %.1f)",
        referrer_id, referred_id, referrer_total,
    )
