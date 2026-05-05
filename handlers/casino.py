"""
Обработчик модуля «Казик».

Логика:
1. Кнопка «🎰 Запустить кампанию» -> валидация доступа.
2. One-time дисклеймер.
3. FSM: ожидание ставки через Inline-кнопки.
4. Спин через Telegram Dice (🎰) и атомарное обновление баланса.
"""

from __future__ import annotations

import logging
import random
from typing import Any, Callable

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import config
from db.models import (
    get_user,
    get_user_casino_daily_spins,
    has_user_flag,
    play_casino_spin_atomic,
    set_user_flag,
)
from keyboards.casino import get_casino_bets_keyboard, get_casino_disclaimer_keyboard
from utils.checks import check_subscription
from utils.timezone import get_kyiv_day_bounds_utc

logger = logging.getLogger(__name__)
router = Router(name="casino")

_CASINO_FLAG_DISCLAIMER = "casino_disclaimer_seen"
_LOSS_KEYS = (
    "casino_loss_1",
    "casino_loss_2",
    "casino_loss_3",
    "casino_loss_4",
)
_SLOT_SYMBOLS = ("bar", "berry", "lemon", "seven")

# Single-process защита от повторных кликов во время анимации.
_spinning_users: set[int] = set()

_casino_logger = logging.getLogger("casino")
if not _casino_logger.handlers:
    file_handler = logging.FileHandler(config.LOGS_DIR / "casino.log", encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            "%Y-%m-%d %H:%M:%S",
        )
    )
    _casino_logger.addHandler(file_handler)
    _casino_logger.setLevel(logging.INFO)
    _casino_logger.propagate = False


class CasinoStates(StatesGroup):
    """FSM-состояния для модуля «Казик»."""

    waiting_for_bet = State()


def _format_balance(value: float) -> str:
    """Красивое форматирование баланса без лишних нулей."""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _available_bets(balance: float) -> list[int]:
    """Список допустимых ставок с правилом balance - bet >= 1."""
    return [
        bet
        for bet in range(1, config.CASINO_MAX_BET + 1)
        if (balance - bet) >= 1
    ]


def _decode_slot_symbols(dice_value: int) -> tuple[str, str, str]:
    """Декодировать значение слота Telegram (1..64) в три символа барабанов."""
    if dice_value < 1 or dice_value > 64:
        raise ValueError("invalid_dice_value")

    raw = dice_value - 1
    left_idx = raw % 4
    middle_idx = (raw // 4) % 4
    right_idx = (raw // 16) % 4

    return (
        _SLOT_SYMBOLS[left_idx],
        _SLOT_SYMBOLS[middle_idx],
        _SLOT_SYMBOLS[right_idx],
    )


def _map_result(dice_value: int) -> tuple[str, float]:
    """Win только за три одинаковых символа, jackpot только за 7-7-7."""
    left, middle, right = _decode_slot_symbols(dice_value)
    if left == middle == right == "seven":
        return "jackpot", 5.0
    if left == middle == right:
        return "win", 3.0
    return "loss", 0.0


async def _daily_spins_count(user_id: int) -> int:
    """Подсчитать число спинов пользователя за текущие сутки Europe/Kiev."""
    day_start_utc, day_end_utc = get_kyiv_day_bounds_utc()
    return await get_user_casino_daily_spins(user_id, day_start_utc, day_end_utc)


async def _validate_casino_entry(
    bot: Bot,
    user_id: int,
    balance: float,
    i18n: Callable,
) -> tuple[bool, str | None, int]:
    """Проверить доступ к казику: подписка, баланс, дневной лимит."""
    try:
        all_subscribed, _ = await check_subscription(bot, user_id)
    except Exception as exc:
        logger.error("Ошибка check_subscription в казино user=%d: %s", user_id, exc)
        _casino_logger.error("user=%d action=entry_check error=subscription_check_failed", user_id)
        return False, i18n("check_error"), 0

    if not all_subscribed:
        _casino_logger.info("user=%d action=entry_check result=fail reason=not_subscribed", user_id)
        return False, i18n("casino_not_subscribed"), 0

    if balance < config.CASINO_MIN_BALANCE:
        _casino_logger.info(
            "user=%d action=entry_check result=fail reason=min_balance balance=%.2f",
            user_id,
            balance,
        )
        return False, i18n("casino_min_balance", min_balance=config.CASINO_MIN_BALANCE), 0

    daily_spins = await _daily_spins_count(user_id)
    if daily_spins >= config.CASINO_DAILY_LIMIT:
        _casino_logger.info(
            "user=%d action=entry_check result=fail reason=daily_limit spins=%d",
            user_id,
            daily_spins,
        )
        return False, i18n("casino_daily_limit", daily_limit=config.CASINO_DAILY_LIMIT), daily_spins

    _casino_logger.info(
        "user=%d action=entry_check result=ok balance=%.2f spins_today=%d",
        user_id,
        balance,
        daily_spins,
    )
    return True, None, daily_spins


async def _show_bet_picker(
    message: Message,
    user_id: int,
    balance: float,
    lang: str,
    i18n: Callable,
    state: FSMContext,
) -> None:
    """Показать клавиатуру выбора ставки, если есть доступные варианты."""
    daily_spins = await _daily_spins_count(user_id)
    available_bets = _available_bets(balance)

    if not available_bets:
        await state.clear()
        await message.answer(i18n("casino_no_bets"))
        return

    await state.set_state(CasinoStates.waiting_for_bet)
    await message.answer(
        i18n(
            "casino_choose_bet",
            balance=_format_balance(balance),
            daily_spins=daily_spins,
            daily_limit=config.CASINO_DAILY_LIMIT,
        ),
        reply_markup=get_casino_bets_keyboard(available_bets, lang),
    )


from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from utils.plugins import get_active_webapp_url

@router.message(F.text == "🎰 Запустить кампанию")
async def start_casino(
    message: Message,
    bot: Bot,
    state: FSMContext,
    i18n: Callable,
    lang: str,
    **kwargs: Any,
) -> None:
    """Точка входа в модуль казино из главного меню."""
    user_id = message.from_user.id

    db_user = await get_user(user_id)
    if not db_user:
        await message.answer(i18n("start"))
        return

    balance = float(db_user["tickets"] or 0.0)
    is_valid, reason, _ = await _validate_casino_entry(bot, user_id, balance, i18n)
    if not is_valid:
        await message.answer(reason)
        return

    await state.clear()
    
    # Отправляем кнопку Web App
    webapp_url = await get_active_webapp_url()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=i18n("menu_casino"), web_app=WebAppInfo(url=webapp_url))]
    ])
    await message.answer("Запускайте кампанию через мини-приложение:", reply_markup=keyboard)


@router.callback_query(F.data == "casino_accept_disclaimer")
async def accept_casino_disclaimer(
    callback: CallbackQuery,
    bot: Bot,
    state: FSMContext,
    i18n: Callable,
    lang: str,
    **kwargs: Any,
) -> None:
    """Подтверждение дисклеймера (показываем один раз на пользователя)."""
    user_id = callback.from_user.id

    if user_id in _spinning_users:
        await callback.answer(i18n("casino_busy"), show_alert=True)
        return

    db_user = await get_user(user_id)
    if not db_user:
        await callback.answer(i18n("check_error"), show_alert=True)
        return

    balance = float(db_user["tickets"] or 0.0)
    is_valid, reason, _ = await _validate_casino_entry(bot, user_id, balance, i18n)
    if not is_valid:
        await callback.answer(reason, show_alert=True)
        return

    await set_user_flag(user_id, _CASINO_FLAG_DISCLAIMER)
    await callback.answer(i18n("casino_disclaimer_saved"))

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await _show_bet_picker(callback.message, user_id, balance, lang, i18n, state)


@router.callback_query(F.data == "casino_cancel")
async def cancel_casino(
    callback: CallbackQuery,
    state: FSMContext,
    i18n: Callable,
    **kwargs: Any,
) -> None:
    """Отмена текущего сценария казино."""
    user_id = callback.from_user.id

    if user_id in _spinning_users:
        await callback.answer(i18n("casino_busy"), show_alert=True)
        return

    await state.clear()
    await callback.answer()

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.message.answer(i18n("casino_cancelled"))


@router.callback_query(F.data.startswith("casino_bet_"))
async def process_casino_bet(
    callback: CallbackQuery,
    bot: Bot,
    state: FSMContext,
    i18n: Callable,
    lang: str,
    **kwargs: Any,
) -> None:
    """Обработка ставки и запуск спина."""
    user_id = callback.from_user.id

    if user_id in _spinning_users:
        await callback.answer(i18n("casino_busy"), show_alert=True)
        return

    current_state = await state.get_state()
    if current_state != CasinoStates.waiting_for_bet.state:
        await callback.answer(i18n("casino_invalid_bet"), show_alert=True)
        return

    try:
        bet = int(callback.data.rsplit("_", maxsplit=1)[1])
    except (ValueError, IndexError):
        await callback.answer(i18n("casino_invalid_bet"), show_alert=True)
        return

    db_user = await get_user(user_id)
    if not db_user:
        await callback.answer(i18n("check_error"), show_alert=True)
        await state.clear()
        return

    balance = float(db_user["tickets"] or 0.0)
    is_valid, reason, _ = await _validate_casino_entry(bot, user_id, balance, i18n)
    if not is_valid:
        await callback.answer(reason, show_alert=True)
        await state.clear()
        return

    if bet not in _available_bets(balance):
        await callback.answer(i18n("casino_invalid_bet"), show_alert=True)
        return

    _spinning_users.add(user_id)
    await state.update_data(spinning=True)

    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.message.answer(i18n("casino_spin_start", bet=bet))

    try:
        dice_message = await bot.send_dice(chat_id=callback.message.chat.id, emoji="🎰")
        dice_value = dice_message.dice.value
        result_type, multiplier = _map_result(dice_value)

        spin_result = await play_casino_spin_atomic(
            user_id=user_id,
            bet_amount=float(bet),
            dice_value=dice_value,
            result_type=result_type,
            multiplier=multiplier,
        )

        daily_spins = await _daily_spins_count(user_id)
        spins_left = max(0, config.CASINO_DAILY_LIMIT - daily_spins)
        balance_after = float(spin_result["balance_after"])
        net_profit = _format_balance(float(spin_result["net_profit"]))

        if result_type == "loss":
            result_text = i18n(random.choice(_LOSS_KEYS))
        elif result_type == "win":
            result_text = i18n("casino_win", net_profit=net_profit)
        else:
            result_text = i18n("casino_jackpot", net_profit=net_profit)

        footer = i18n(
            "casino_result_footer",
            balance=_format_balance(balance_after),
            spins_left=spins_left,
        )

        await callback.message.answer(f"{result_text}\n\n{footer}")

        _casino_logger.info(
            (
                "user=%d action=spin bet=%.2f dice=%d result=%s multiplier=%.1f "
                "balance_before=%.2f balance_after=%.2f net=%.2f spins_today=%d"
            ),
            user_id,
            float(spin_result["bet_amount"]),
            dice_value,
            result_type,
            float(spin_result["multiplier"]),
            float(spin_result["balance_before"]),
            balance_after,
            float(spin_result["net_profit"]),
            daily_spins,
        )

        available_bets = _available_bets(balance_after)
        can_continue = (
            balance_after >= config.CASINO_MIN_BALANCE
            and spins_left > 0
            and bool(available_bets)
        )

        if can_continue:
            await state.set_state(CasinoStates.waiting_for_bet)
            await callback.message.answer(
                i18n(
                    "casino_choose_bet",
                    balance=_format_balance(balance_after),
                    daily_spins=daily_spins,
                    daily_limit=config.CASINO_DAILY_LIMIT,
                ),
                reply_markup=get_casino_bets_keyboard(available_bets, lang),
            )
        else:
            await state.clear()
            if balance_after < config.CASINO_MIN_BALANCE:
                await callback.message.answer(
                    i18n("casino_min_balance", min_balance=config.CASINO_MIN_BALANCE),
                )
            elif spins_left <= 0:
                await callback.message.answer(
                    i18n("casino_daily_limit", daily_limit=config.CASINO_DAILY_LIMIT),
                )
            else:
                await callback.message.answer(i18n("casino_no_bets"))

    except ValueError as exc:
        _casino_logger.error(
            "user=%d action=spin error=value_error details=%s",
            user_id,
            exc,
        )
        await callback.message.answer(i18n("casino_tx_error"))
    except Exception as exc:
        logger.error("Ошибка спина casino user=%d: %s", user_id, exc, exc_info=True)
        _casino_logger.error(
            "user=%d action=spin error=exception details=%s",
            user_id,
            exc,
        )
        await callback.message.answer(i18n("casino_tx_error"))
    finally:
        _spinning_users.discard(user_id)
        await state.update_data(spinning=False)
