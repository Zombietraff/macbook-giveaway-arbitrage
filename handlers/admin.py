"""
Админ-команды для управления конкурсом.

- /admin_stats — статистика конкурса.
- /set_date YYYY-MM-DD HH:MM — установка или продление даты окончания.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from html import escape
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    MessageEntity,
    WebAppInfo,
)

import config
from db.database import get_db
from db.models import (
    add_admin_audit_log,
    add_channel,
    add_promocode,
    add_temporary_admin,
    clear_contest_prizes,
    clear_winners,
    get_all_channels,
    get_all_promocodes,
    get_casino_stats,
    get_contest_prizes,
    get_contest_reset_preview,
    get_contest_reset_runs,
    get_end_date,
    get_temporary_admins,
    get_trust_stats,
    remove_channel as delete_channel,
    reset_contest_with_archive,
    revoke_temporary_admin,
    set_contest_prizes,
    set_end_date,
    set_user_blocked,
)
from keyboards.main_menu import get_active_main_menu_keyboard
from utils.admin_access import can_manage_contest, can_manage_system, is_owner
from utils.plugins import get_active_plugin_key, get_active_webapp_url, list_plugins, set_active_plugin_key
from utils.timezone import get_kyiv_day_bounds_utc
from utils.webapp_launch import build_webapp_launch_url

logger = logging.getLogger(__name__)
router = Router(name="admin")

# Файл лога для действий админа
_ADMIN_LOG = config.LOGS_DIR / "admin.log"

_SEND_CONFIRM_DATA = "send_confirm"
_SEND_CANCEL_DATA = "send_cancel"
_ADMIN_MENU_PREFIX = "admin_menu:"
_RESET_CONFIRM_PREFIX = "reset_contest:confirm:"
_RESET_CANCEL_PREFIX = "reset_contest:cancel:"


class AdminSendState(StatesGroup):
    """FSM-состояние для подтверждения админ-рассылки /send."""

    waiting_message = State()
    waiting_button_choice = State()
    waiting_button_text = State()
    waiting_confirm = State()


class AdminPrizeState(StatesGroup):
    """FSM-состояние для многострочной настройки призов."""

    waiting_prizes = State()


async def _is_admin(user_id: int) -> bool:
    """Проверить, является ли пользователь администратором."""
    return await can_manage_contest(user_id)


def _is_owner(user_id: int) -> bool:
    """Проверить, является ли пользователь owner-ом."""
    return can_manage_system(user_id)


def _log_admin_action(admin_id: int, action: str) -> None:
    """Записать действие администратора в лог-файл."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] admin={admin_id} action={action}\n"
    with open(_ADMIN_LOG, "a", encoding="utf-8") as f:
        f.write(line)
    logger.info("Admin action: %s (by %d)", action, admin_id)
    try:
        asyncio.create_task(add_admin_audit_log(admin_id, action))
    except RuntimeError:
        pass


def _fmt_amount(value: float) -> str:
    """Форматировать число без лишних нулей после запятой."""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _parse_prize_lines(text: str) -> list[tuple[int, str]]:
    """Разобрать строки формата '<quantity> | <prize name>'."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("укажите хотя бы один приз")

    prizes: list[tuple[int, str]] = []
    for idx, line in enumerate(lines, start=1):
        if "|" not in line:
            raise ValueError(f"строка {idx}: нужен разделитель |")

        quantity_raw, name_raw = line.split("|", maxsplit=1)
        try:
            quantity = int(quantity_raw.strip())
        except ValueError as exc:
            raise ValueError(f"строка {idx}: количество должно быть целым числом") from exc

        name = name_raw.strip()
        if quantity <= 0:
            raise ValueError(f"строка {idx}: количество должно быть больше 0")
        if not name:
            raise ValueError(f"строка {idx}: название приза пустое")
        if len(name) > 120:
            raise ValueError(f"строка {idx}: название приза слишком длинное")

        prizes.append((quantity, name))

    return prizes


def _format_prize_rows(prizes: list[Any]) -> str:
    """Сформировать человекочитаемый список призов."""
    if not prizes:
        return "📭 Призы конкурса не настроены."

    total = sum(int(row["quantity"]) for row in prizes)
    lines = [f"🏆 <b>Призы конкурса</b>\nВсего победителей: <b>{total}</b>"]
    for row in prizes:
        lines.append(
            f"{int(row['position'])}. <b>{int(row['quantity'])}</b> × "
            f"{escape(str(row['name']))}"
        )
    return "\n".join(lines)


def _get_send_preview_keyboard() -> InlineKeyboardMarkup:
    """Inline-кнопки подтверждения/отмены рассылки /send."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отправить", callback_data=_SEND_CONFIRM_DATA),
                InlineKeyboardButton(text="❌ Отмена", callback_data=_SEND_CANCEL_DATA),
            ]
        ]
    )


def _get_reset_preview_keyboard(owner_id: int) -> InlineKeyboardMarkup:
    """Inline-кнопки подтверждения/отмены owner reset."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить сброс",
                    callback_data=f"{_RESET_CONFIRM_PREFIX}{owner_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data=f"{_RESET_CANCEL_PREFIX}{owner_id}",
                ),
            ]
        ]
    )


def _get_admin_menu_keyboard(owner: bool) -> InlineKeyboardMarkup:
    """Inline-меню админки с owner/operational разделами."""
    rows = [
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data=f"{_ADMIN_MENU_PREFIX}stats"),
            InlineKeyboardButton(text="📣 Рассылка", callback_data=f"{_ADMIN_MENU_PREFIX}send"),
        ],
        [
            InlineKeyboardButton(text="📅 Дата розыгрыша", callback_data=f"{_ADMIN_MENU_PREFIX}date"),
            InlineKeyboardButton(text="📢 Каналы", callback_data=f"{_ADMIN_MENU_PREFIX}channels"),
        ],
        [
            InlineKeyboardButton(text="🏆 Призы", callback_data=f"{_ADMIN_MENU_PREFIX}prizes"),
        ],
        [
            InlineKeyboardButton(text="🥚 Промокоды", callback_data=f"{_ADMIN_MENU_PREFIX}promos"),
        ],
    ]
    if owner:
        rows.extend(
            [
                [
                    InlineKeyboardButton(text="👑 Временные админы", callback_data=f"{_ADMIN_MENU_PREFIX}admins"),
                    InlineKeyboardButton(text="🎮 Мини-игры", callback_data=f"{_ADMIN_MENU_PREFIX}plugins"),
                ],
                [
                    InlineKeyboardButton(text="⚙️ Система", callback_data=f"{_ADMIN_MENU_PREFIX}system"),
                    InlineKeyboardButton(text="🧹 Сброс конкурса", callback_data=f"{_ADMIN_MENU_PREFIX}reset"),
                ],
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


_ADMIN_MENU_HELP = {
    "stats": "📊 Статистика: /admin_stats или /casino_stats",
    "send": "📣 Рассылка: /send текст сообщения",
    "date": "📅 Дата: /set_date YYYY-MM-DD HH:MM",
    "channels": (
        "📢 Каналы:\n"
        "/list_channels\n"
        "/add_channel <channel_id> | <title> | <invite_link>\n"
        "/remove_channel <channel_id>"
    ),
    "prizes": (
        "🏆 Призы конкурса:\n"
        "/set_prizes — задать список через многострочный ввод\n"
        "/list_prizes — показать текущий список\n"
        "/clear_prizes — очистить список"
    ),
    "promos": (
        "🥚 Промокоды:\n"
        "/add_promocode <code>\n"
        "/add_promocodes <code1> <code2> ..."
    ),
    "admins": "👑 Временные админы: /list_admins, /add_admin <telegram_id>, /remove_admin <telegram_id>",
    "plugins": "🎮 Мини-игры: /list_plugins, /set_plugin <plugin_key>",
    "system": "⚙️ Система: /webapp_url, /refresh_menu, /list_plugins, /trust_stats, /reset_history",
    "reset": "🧹 Сброс конкурса: /reset_contest. История сбросов: /reset_history",
}


def _extract_send_payload(message: Message) -> tuple[str, list[MessageEntity], str | None]:
    """Извлечь текст после /send, сохранить исходные форматирующие entities и photo_file_id."""
    text = message.text or message.caption or ""
    photo_file_id = message.photo[-1].file_id if message.photo else None
    if not text:
        return "", [], photo_file_id

    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return "", [], photo_file_id

    command_token = parts[0]
    # Check if the command is exactly /send (in case of caption without command)
    if not command_token.startswith("/send"):
        # If it's a message in waiting_message state, it might not have /send.
        # But this function is only called on the initial message with /send.
        pass

    payload_start = len(command_token)
    while payload_start < len(text) and text[payload_start].isspace():
        payload_start += 1

    payload_text = text[payload_start:]
    payload_entities: list[MessageEntity] = []

    # get entities or caption_entities
    entities = message.entities or message.caption_entities or []

    for entity in entities:
        entity_start = entity.offset
        entity_end = entity.offset + entity.length

        # Пропускаем entities, относящиеся к /send.
        if entity_end <= payload_start:
            continue

        # Некорректные пересечения с префиксом команды игнорируем.
        if entity_start < payload_start:
            continue

        payload_entities.append(
            entity.model_copy(update={"offset": entity_start - payload_start})
        )

    return payload_text, payload_entities, photo_file_id


def _format_reset_preview(preview: dict[str, int | float]) -> str:
    """Сформировать текст preview/summary для owner reset."""
    return (
        "🧹 <b>Сброс конкурса</b>\n\n"
        "Перед очисткой данные будут архивированы в историю reset.\n\n"
        f"👥 Users с tickets: <b>{preview['users_with_tickets_count']}</b>\n"
        f"🎫 Tickets всего: <b>{_fmt_amount(float(preview['total_tickets']))}</b>\n"
        f"🏆 Winners: <b>{preview['winners_count']}</b>\n"
        f"🎰 Casino spins: <b>{preview['casino_spins_count']}</b>\n"
        f"📢 Channels: <b>{preview['channels_count']}</b>\n"
        f"🥚 Promocodes: <b>{preview['promocodes_count']}</b>\n"
        f"🕵️ Trust scores: <b>{preview['trust_scores_count']}</b>\n"
        f"🛠 Active temp admins: <b>{preview['active_temp_admins_count']}</b>\n\n"
        "Будут очищены tickets, trust scores, winners, spins, channels, promocodes и temporary admins. "
        "Users, referrals, settings, user_flags и audit log останутся."
    )


@router.message(Command("admin_menu"))
async def admin_menu(message: Message, **kwargs: Any) -> None:
    """Показать админское меню по роли пользователя."""
    user_id = message.from_user.id
    if not await _is_admin(user_id):
        return

    owner = _is_owner(user_id)
    title = "👑 <b>Owner admin panel</b>" if owner else "🛠 <b>Temporary admin panel</b>"
    await message.answer(
        title + "\nВыберите раздел или используйте slash-команды.",
        reply_markup=_get_admin_menu_keyboard(owner),
    )
    _log_admin_action(user_id, "admin_menu")


@router.message(Command("owner_menu"))
async def owner_menu(message: Message, **kwargs: Any) -> None:
    """Показать owner-only меню."""
    if not _is_owner(message.from_user.id):
        return

    await message.answer(
        "👑 <b>Owner panel</b>\n"
        "Доступы, мини-игры и системные настройки.",
        reply_markup=_get_admin_menu_keyboard(owner=True),
    )
    _log_admin_action(message.from_user.id, "owner_menu")


@router.callback_query(F.data.startswith(_ADMIN_MENU_PREFIX))
async def admin_menu_help(callback: CallbackQuery, **kwargs: Any) -> None:
    """Подсказки по разделам inline-админки."""
    user_id = callback.from_user.id
    if not await _is_admin(user_id):
        await callback.answer()
        return

    section = callback.data.removeprefix(_ADMIN_MENU_PREFIX)
    if section in {"admins", "plugins", "system", "reset"} and not _is_owner(user_id):
        await callback.answer("Owner-only раздел", show_alert=True)
        return

    await callback.answer()
    if callback.message:
        await callback.message.answer(_ADMIN_MENU_HELP.get(section, "Раздел не найден."))


@router.message(Command("add_admin"))
async def add_temp_admin(message: Message, bot: Bot, **kwargs: Any) -> None:
    """Добавить временного админа (owner-only)."""
    if not _is_owner(message.from_user.id):
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().lstrip("-").isdigit():
        await message.answer("⚠️ Формат: <code>/add_admin telegram_id</code>")
        return

    target_id = int(parts[1].strip())
    username = None
    first_name = None
    try:
        chat = await bot.get_chat(target_id)
        username = getattr(chat, "username", None)
        first_name = getattr(chat, "first_name", None)
    except Exception:
        pass

    await add_temporary_admin(
        user_id=target_id,
        added_by=message.from_user.id,
        username=username,
        first_name=first_name,
    )
    await add_admin_audit_log(message.from_user.id, "add_temp_admin", target_id)
    await message.answer(f"✅ Временный админ добавлен: <code>{target_id}</code>")
    _log_admin_action(message.from_user.id, f"add_temp_admin: {target_id}")


@router.message(Command("remove_admin"))
async def remove_temp_admin(message: Message, **kwargs: Any) -> None:
    """Снять временного админа (owner-only)."""
    if not _is_owner(message.from_user.id):
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().lstrip("-").isdigit():
        await message.answer("⚠️ Формат: <code>/remove_admin telegram_id</code>")
        return

    target_id = int(parts[1].strip())
    await revoke_temporary_admin(target_id)
    await add_admin_audit_log(message.from_user.id, "remove_temp_admin", target_id)
    await message.answer(f"✅ Временный админ снят: <code>{target_id}</code>")
    _log_admin_action(message.from_user.id, f"remove_temp_admin: {target_id}")


@router.message(Command("list_admins"))
async def list_temp_admins(message: Message, **kwargs: Any) -> None:
    """Показать активных временных админов (owner-only)."""
    if not _is_owner(message.from_user.id):
        return

    admins = await get_temporary_admins()
    if not admins:
        await message.answer("📭 Активных временных админов нет.")
        return

    lines = ["👑 <b>Owner IDs</b>: " + ", ".join(map(str, config.OWNER_IDS)), "\n🛠 <b>Временные админы</b>"]
    for admin in admins:
        name = admin["username"] or admin["first_name"] or "—"
        lines.append(f"• <code>{admin['user_id']}</code> ({name}), добавил: <code>{admin['added_by']}</code>")
    await message.answer("\n".join(lines))
    _log_admin_action(message.from_user.id, "list_admins")


@router.message(Command("list_channels"))
async def list_required_channels(message: Message, **kwargs: Any) -> None:
    """Показать обязательные каналы."""
    if not await _is_admin(message.from_user.id):
        return

    channels = await get_all_channels()
    if not channels:
        await message.answer("📭 Каналов обязательной подписки нет.")
        return

    lines = ["📢 <b>Каналы обязательной подписки</b>"]
    for channel in channels:
        lines.append(
            f"• <code>{channel['channel_id']}</code>\n"
            f"  {channel['title']}\n"
            f"  {channel['invite_link']}"
        )
    await message.answer("\n".join(lines))
    _log_admin_action(message.from_user.id, "list_channels")


@router.message(Command("add_channel"))
async def admin_add_channel(message: Message, **kwargs: Any) -> None:
    """Добавить канал обязательной подписки."""
    if not await _is_admin(message.from_user.id):
        return

    payload = (message.text or "").split(maxsplit=1)
    if len(payload) < 2:
        await message.answer("⚠️ Формат: <code>/add_channel channel_id | title | invite_link</code>")
        return

    parts = [part.strip() for part in payload[1].split("|")]
    if len(parts) != 3 or not all(parts):
        await message.answer("⚠️ Формат: <code>/add_channel channel_id | title | invite_link</code>")
        return

    channel_id, title, invite_link = parts
    await add_channel(channel_id, title, invite_link)
    await add_admin_audit_log(
        message.from_user.id,
        "add_channel",
        payload={"channel_id": channel_id, "title": title, "invite_link": invite_link},
    )
    await message.answer(f"✅ Канал добавлен: <b>{title}</b> (<code>{channel_id}</code>)")
    _log_admin_action(message.from_user.id, f"add_channel: {channel_id}")


@router.message(Command("remove_channel"))
async def admin_remove_channel(message: Message, **kwargs: Any) -> None:
    """Удалить канал обязательной подписки."""
    if not await _is_admin(message.from_user.id):
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("⚠️ Формат: <code>/remove_channel channel_id</code>")
        return

    channel_id = parts[1].strip()
    await delete_channel(channel_id)
    await add_admin_audit_log(message.from_user.id, "remove_channel", payload={"channel_id": channel_id})
    await message.answer(f"✅ Канал удалён: <code>{channel_id}</code>")
    _log_admin_action(message.from_user.id, f"remove_channel: {channel_id}")


@router.message(Command("add_promocode"))
async def admin_add_promocode(message: Message, **kwargs: Any) -> None:
    """Добавить один промокод."""
    if not await _is_admin(message.from_user.id):
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer("⚠️ Формат: <code>/add_promocode code</code>")
        return

    code = parts[1].strip()
    await add_promocode(code)
    await add_admin_audit_log(message.from_user.id, "add_promocode", payload={"code": code})
    await message.answer(f"✅ Промокод добавлен: <code>{code}</code>")
    _log_admin_action(message.from_user.id, f"add_promocode: {code}")


@router.message(Command("add_promocodes"))
async def admin_add_promocodes(message: Message, **kwargs: Any) -> None:
    """Добавить несколько промокодов через пробел или новую строку."""
    if not await _is_admin(message.from_user.id):
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("⚠️ Формат: <code>/add_promocodes code1 code2 ...</code>")
        return

    codes = [code.strip() for code in parts[1].replace("\n", " ").split(" ") if code.strip()]
    if not codes:
        await message.answer("⚠️ Укажите хотя бы один промокод.")
        return

    for code in codes:
        await add_promocode(code)

    await add_admin_audit_log(message.from_user.id, "add_promocodes", payload={"count": len(codes)})
    await message.answer(f"✅ Промокоды добавлены: <b>{len(codes)}</b>")
    _log_admin_action(message.from_user.id, f"add_promocodes: {len(codes)}")


@router.message(Command("set_prizes"))
async def admin_set_prizes_start(
    message: Message,
    state: FSMContext,
    **kwargs: Any,
) -> None:
    """Запустить настройку призов конкурса или принять inline payload."""
    if not await _is_admin(message.from_user.id):
        return

    payload = (message.text or "").split(maxsplit=1)
    if len(payload) > 1 and payload[1].strip():
        try:
            prizes = _parse_prize_lines(payload[1])
        except ValueError as exc:
            await message.answer(f"❌ Ошибка в списке призов: {escape(str(exc))}")
            return

        await set_contest_prizes(prizes, created_by=message.from_user.id)
        await add_admin_audit_log(
            message.from_user.id,
            "set_prizes",
            payload={"total": sum(quantity for quantity, _ in prizes), "items": prizes},
        )
        await message.answer(_format_prize_rows(await get_contest_prizes()))
        _log_admin_action(message.from_user.id, f"set_prizes: {len(prizes)} rows")
        return

    await state.set_state(AdminPrizeState.waiting_prizes)
    await message.answer(
        "🏆 Отправьте список призов строками в формате:\n"
        "<code>1 | Главный приз</code>\n"
        "<code>3 | Приз второго уровня</code>\n"
        "<code>5 | Бонусный приз</code>\n\n"
        "Порядок сверху вниз будет порядком выдачи: сначала лучшие призы.\n"
        "Для отмены отправьте /cancel."
    )
    _log_admin_action(message.from_user.id, "set_prizes_started")


@router.message(AdminPrizeState.waiting_prizes, Command("cancel"))
async def admin_set_prizes_cancel(
    message: Message,
    state: FSMContext,
    **kwargs: Any,
) -> None:
    """Отменить многострочный ввод призов."""
    if not await _is_admin(message.from_user.id):
        await state.clear()
        return

    await state.clear()
    await message.answer("❌ Настройка призов отменена.")
    _log_admin_action(message.from_user.id, "set_prizes_cancelled")


@router.message(AdminPrizeState.waiting_prizes, F.text.startswith("/"))
async def admin_set_prizes_command_during_input(
    message: Message,
    state: FSMContext,
    **kwargs: Any,
) -> None:
    """Не парсить slash-команды как строки призов."""
    if not await _is_admin(message.from_user.id):
        await state.clear()
        return

    await state.clear()
    await message.answer(
        "❌ Настройка призов отменена. Команда не была выполнена, отправьте её ещё раз."
    )
    _log_admin_action(message.from_user.id, "set_prizes_cancelled_by_command")


@router.message(AdminPrizeState.waiting_prizes)
async def admin_set_prizes_receive(
    message: Message,
    state: FSMContext,
    **kwargs: Any,
) -> None:
    """Принять многострочный список призов для /set_prizes."""
    if not await _is_admin(message.from_user.id):
        await state.clear()
        return

    text = message.text or ""
    if text.strip().lower() in {"/cancel", "cancel", "отмена"}:
        await state.clear()
        await message.answer("❌ Настройка призов отменена.")
        return

    try:
        prizes = _parse_prize_lines(text)
    except ValueError as exc:
        await message.answer(
            f"❌ Ошибка в списке призов: {escape(str(exc))}\n\n"
            "Старый список не изменён. Исправьте сообщение и отправьте ещё раз."
        )
        return

    await set_contest_prizes(prizes, created_by=message.from_user.id)
    await add_admin_audit_log(
        message.from_user.id,
        "set_prizes",
        payload={"total": sum(quantity for quantity, _ in prizes), "items": prizes},
    )
    await state.clear()
    await message.answer(_format_prize_rows(await get_contest_prizes()))
    _log_admin_action(message.from_user.id, f"set_prizes: {len(prizes)} rows")


@router.message(Command("list_prizes"))
async def admin_list_prizes(message: Message, **kwargs: Any) -> None:
    """Показать текущий список призов конкурса."""
    if not await _is_admin(message.from_user.id):
        return

    await message.answer(_format_prize_rows(await get_contest_prizes()))
    _log_admin_action(message.from_user.id, "list_prizes")


@router.message(Command("clear_prizes"))
async def admin_clear_prizes(message: Message, **kwargs: Any) -> None:
    """Очистить список призов конкурса."""
    if not await _is_admin(message.from_user.id):
        return

    await clear_contest_prizes()
    await add_admin_audit_log(message.from_user.id, "clear_prizes")
    await message.answer("✅ Список призов очищен. /draw будет заблокирован до новой настройки призов.")
    _log_admin_action(message.from_user.id, "clear_prizes")


@router.message(Command("list_plugins"))
async def admin_list_plugins(message: Message, **kwargs: Any) -> None:
    """Показать доступные мини-игры."""
    if not await _is_admin(message.from_user.id):
        return

    active_key = await get_active_plugin_key()
    plugins = list_plugins(include_disabled=True)
    if not plugins:
        await message.answer("📭 Мини-игры не найдены.")
        return

    lines = ["🎮 <b>Мини-игры</b>"]
    for plugin in plugins:
        marker = "✅" if plugin.key == active_key else "•"
        status = "enabled" if plugin.enabled else "disabled"
        lines.append(f"{marker} <code>{plugin.key}</code> — {plugin.name} ({status})")
    await message.answer("\n".join(lines))
    _log_admin_action(message.from_user.id, "list_plugins")


@router.message(Command("set_plugin"))
async def admin_set_plugin(message: Message, **kwargs: Any) -> None:
    """Выбрать активную мини-игру (owner-only)."""
    if not _is_owner(message.from_user.id):
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("⚠️ Формат: <code>/set_plugin plugin_key</code>")
        return

    plugin_key = parts[1].strip()
    try:
        plugin = await set_active_plugin_key(plugin_key)
    except ValueError:
        await message.answer("❌ Неизвестный plugin_key. Посмотрите /list_plugins.")
        return

    await add_admin_audit_log(message.from_user.id, "set_plugin", payload={"plugin_key": plugin.key})
    await message.answer(f"✅ Активная мини-игра: <code>{plugin.key}</code> — {plugin.name}")
    _log_admin_action(message.from_user.id, f"set_plugin: {plugin.key}")


@router.message(Command("reset_contest"))
async def reset_contest_preview(message: Message, **kwargs: Any) -> None:
    """Показать owner-only preview перед сбросом конкурса."""
    owner_id = message.from_user.id
    if not _is_owner(owner_id):
        return

    preview = await get_contest_reset_preview()
    await add_admin_audit_log(owner_id, "reset_contest_preview", payload=preview)
    await message.answer(
        _format_reset_preview(preview),
        reply_markup=_get_reset_preview_keyboard(owner_id),
    )
    _log_admin_action(owner_id, "reset_contest_preview")


@router.callback_query(F.data.startswith(_RESET_CANCEL_PREFIX))
async def reset_contest_cancel(callback: CallbackQuery, **kwargs: Any) -> None:
    """Отменить owner reset из preview-кнопки."""
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return

    owner_id_raw = callback.data.removeprefix(_RESET_CANCEL_PREFIX)
    if not owner_id_raw.isdigit() or int(owner_id_raw) != callback.from_user.id:
        await callback.answer("Это подтверждение создано другим owner-ом.", show_alert=True)
        return

    await add_admin_audit_log(callback.from_user.id, "reset_contest_cancelled")
    await callback.answer("Сброс отменён")
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.message.answer("❌ Сброс конкурса отменён.")
    _log_admin_action(callback.from_user.id, "reset_contest_cancelled")


@router.callback_query(F.data.startswith(_RESET_CONFIRM_PREFIX))
async def reset_contest_confirm(callback: CallbackQuery, **kwargs: Any) -> None:
    """Подтвердить owner reset, архивировать данные и очистить конкурс."""
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return

    owner_id_raw = callback.data.removeprefix(_RESET_CONFIRM_PREFIX)
    if not owner_id_raw.isdigit() or int(owner_id_raw) != callback.from_user.id:
        await callback.answer("Это подтверждение создано другим owner-ом.", show_alert=True)
        return

    await callback.answer("Сбрасываю конкурс...")
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    result = await reset_contest_with_archive(callback.from_user.id)
    await add_admin_audit_log(
        callback.from_user.id,
        "reset_contest_confirmed",
        target_id=int(result["reset_id"]),
        payload=result,
    )

    summary = (
        "✅ <b>Конкурс сброшен</b>\n\n"
        f"Archive reset id: <code>{int(result['reset_id'])}</code>\n\n"
        f"👥 Users с tickets: <b>{result['users_with_tickets_count']}</b>\n"
        f"🎫 Tickets сброшено: <b>{_fmt_amount(float(result['total_tickets']))}</b>\n"
        f"🏆 Winners очищено: <b>{result['winners_count']}</b>\n"
        f"🎰 Spins очищено: <b>{result['casino_spins_count']}</b>\n"
        f"📢 Channels очищено: <b>{result['channels_count']}</b>\n"
        f"🥚 Promocodes очищено: <b>{result['promocodes_count']}</b>\n"
        f"🕵️ Trust scores очищено: <b>{result['trust_scores_count']}</b>\n"
        f"🛠 Temp admins очищено: <b>{result['temp_admins_count']}</b>"
    )
    if callback.message:
        await callback.message.answer(summary)
    _log_admin_action(callback.from_user.id, f"reset_contest_confirmed: {int(result['reset_id'])}")


@router.message(Command("reset_history"))
async def reset_history(message: Message, **kwargs: Any) -> None:
    """Показать последние owner reset runs."""
    if not _is_owner(message.from_user.id):
        return

    runs = await get_contest_reset_runs(limit=10)
    if not runs:
        await message.answer("📭 История сбросов пуста.")
        return

    lines = ["🧹 <b>История сбросов конкурса</b>"]
    for run in runs:
        lines.append(
            "\n"
            f"ID: <code>{run['id']}</code>\n"
            f"Дата: <code>{run['created_at']}</code>\n"
            f"Owner: <code>{run['actor_id']}</code>\n"
            f"Users/tickets: <b>{run['users_with_tickets_count']}</b> / "
            f"<b>{_fmt_amount(float(run['total_tickets']))}</b>\n"
            f"Winners/spins/channels/promos/temp admins: "
            f"<b>{run['winners_count']}</b> / "
            f"<b>{run['casino_spins_count']}</b> / "
            f"<b>{run['channels_count']}</b> / "
            f"<b>{run['promocodes_count']}</b> / "
            f"<b>{run['temp_admins_count']}</b>"
            f"\nTrust scores: <b>{run['trust_scores_count']}</b>"
        )
    await message.answer("\n".join(lines))
    _log_admin_action(message.from_user.id, "reset_history")


@router.message(Command("trust_stats"))
async def trust_stats(message: Message, **kwargs: Any) -> None:
    """Показать owner-only агрегаты скрытого trust score."""
    if not _is_owner(message.from_user.id):
        return

    stats = await get_trust_stats()
    text = (
        "🕵️ <b>Hidden trust stats</b>\n\n"
        f"Всего проверок: <b>{stats['total']}</b>\n"
        f"Boosted x5: <b>{stats['boosted']}</b>\n"
        f"Plain x1: <b>{stats['plain']}</b>\n"
        f"Unresolvable: <b>{stats['unresolvable']}</b>\n"
        f"Errors: <b>{stats['error']}</b>\n"
        f"Disabled: <b>{stats['disabled']}</b>\n\n"
        f"3+ common groups: <b>{stats['strong_common_3_plus']}</b>\n"
        f"Avg common groups: <b>{stats['avg_common_chat_count']:.2f}</b>\n"
        f"Max common groups: <b>{stats['max_common_chat_count']}</b>"
    )
    await message.answer(text)
    _log_admin_action(message.from_user.id, "trust_stats")


@router.message(Command("admin_stats"))
async def admin_stats(message: Message, **kwargs: Any) -> None:
    """Показать статистику конкурса (только для админов)."""
    if not await _is_admin(message.from_user.id):
        return

    db = await get_db()

    async with db.execute("SELECT COUNT(*) FROM users") as cur:
        total_users = (await cur.fetchone())[0]
    async with db.execute("SELECT COUNT(*) FROM users WHERE tickets > 0") as cur:
        active_users = (await cur.fetchone())[0]
    async with db.execute("SELECT SUM(tickets) FROM users") as cur:
        total_tickets = (await cur.fetchone())[0] or 0
    async with db.execute("SELECT COUNT(*) FROM referrals WHERE status='completed'") as cur:
        total_referrals = (await cur.fetchone())[0]
    async with db.execute("SELECT COUNT(*) FROM promocodes WHERE used_by IS NOT NULL") as cur:
        used_promos = (await cur.fetchone())[0]
    async with db.execute("SELECT COUNT(*) FROM users WHERE blocked_bot=TRUE") as cur:
        blocked = (await cur.fetchone())[0]

    end_date = await get_end_date()
    end_date_str = end_date.strftime('%Y-%m-%d %H:%M') if end_date else "Не установлена"

    text = (
        "📊 <b>Статистика конкурса</b>\n\n"
        f"👥 Всего пользователей: <b>{total_users}</b>\n"
        f"✅ Активных участников: <b>{active_users}</b>\n"
        f"🎫 Всего билетов: <b>{int(total_tickets)}</b>\n"
        f"👥 Рефералов (completed): <b>{total_referrals}</b>\n"
        f"🥚 Промокодов использовано: <b>{used_promos}</b>\n"
        f"🚫 Заблокировали бота: <b>{blocked}</b>\n\n"
        f"📅 Дата окончания: <b>{end_date_str}</b>"
    )

    await message.answer(text)
    _log_admin_action(message.from_user.id, "admin_stats")


@router.message(Command("set_date"))
async def set_date(message: Message, **kwargs: Any) -> None:
    """Установить или продлить дату окончания конкурса (только для админов)."""
    if not await _is_admin(message.from_user.id):
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "⚠️ Формат: <code>/set_date YYYY-MM-DD HH:MM</code>",
        )
        return

    date_str = parts[1].strip()
    try:
        new_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
    except ValueError:
        await message.answer(
            "❌ Неверный формат даты. Используйте: <code>YYYY-MM-DD HH:MM</code>",
        )
        return

    old_date = await get_end_date()
    old_date_str = old_date.strftime('%Y-%m-%d %H:%M') if old_date else "Не установлена"
    
    await set_end_date(new_date)
    await clear_winners()

    await message.answer(
        f"✅ Дата окончания обновлена:\n"
        f"Было: <b>{old_date_str}</b>\n"
        f"Стало: <b>{new_date.strftime('%Y-%m-%d %H:%M')}</b>\n\n"
        f"🧹 <i>Предыдущие победители сброшены.</i>",
    )

    _log_admin_action(
        message.from_user.id,
        f"set_date: {old_date_str} → {new_date}",
    )


@router.message(Command("casino_stats"))
async def casino_stats(message: Message, **kwargs: Any) -> None:
    """Показать статистику модуля казино (только для админов)."""
    if not await _is_admin(message.from_user.id):
        return

    day_start_utc, day_end_utc = get_kyiv_day_bounds_utc()
    stats = await get_casino_stats(day_start_utc, day_end_utc)

    top_players = stats["top_players"]
    if top_players:
        top_lines = [
            f"{idx}. {player['display_name']} — <b>{player['spins']}</b>"
            for idx, player in enumerate(top_players, 1)
        ]
        top_text = "\n".join(top_lines)
    else:
        top_text = "—"

    text = (
        "🎰 <b>Casino stats</b>\n\n"
        f"🗓 Спинов сегодня: <b>{stats['today_spins']}</b>\n"
        f"📦 Спинов всего: <b>{stats['total_spins']}</b>\n\n"
        f"💵 Ставок сегодня: <b>{_fmt_amount(stats['today_bets'])}</b>\n"
        f"💸 Выплат сегодня: <b>{_fmt_amount(stats['today_payouts'])}</b>\n"
        f"💰 Ставок всего: <b>{_fmt_amount(stats['total_bets'])}</b>\n"
        f"🏧 Выплат всего: <b>{_fmt_amount(stats['total_payouts'])}</b>\n"
        f"📈 House profit: <b>{_fmt_amount(stats['house_profit'])}</b>\n"
        f"🎯 Winrate: <b>{stats['win_rate']:.2f}%</b>\n\n"
        f"🔴 Loss: <b>{stats['breakdown']['loss']}</b>\n"
        f"🟢 Win: <b>{stats['breakdown']['win']}</b>\n"
        f"🎰 Jackpot: <b>{stats['breakdown']['jackpot']}</b>\n\n"
        f"🏆 Топ-3 игроков по спинам:\n{top_text}"
    )

    await message.answer(text)
    _log_admin_action(message.from_user.id, "casino_stats")


@router.message(Command("webapp_url"))
async def webapp_url(message: Message, bot: Bot, **kwargs: Any) -> None:
    """Показать текущий WEBAPP_URL и выдать свежую reply-клавиатуру."""
    if not _is_owner(message.from_user.id):
        return

    webapp_url_value = await get_active_webapp_url()
    menu_url = build_webapp_launch_url(webapp_url_value, message.from_user.id)
    menu_update_failed = False
    menu_button = MenuButtonWebApp(
        text="🎰 Запустить кампанию",
        web_app=WebAppInfo(url=menu_url),
    )

    try:
        await bot.set_chat_menu_button(menu_button=menu_button)
        await bot.set_chat_menu_button(chat_id=message.chat.id, menu_button=menu_button)
    except Exception as exc:
        menu_update_failed = True
        logger.warning("webapp_url: menu button update failed for chat=%s: %s", message.chat.id, exc)

    await message.answer(
        "🔗 <b>Текущий WEBAPP_URL</b>\n"
        f"<code>{config.WEBAPP_URL}</code>\n\n"
        f"🎮 Активная мини-игра URL:\n<code>{webapp_url_value}</code>\n\n"
        f"{'⚠️ Нижнюю WebApp-кнопку не удалось обновить автоматически.\n' if menu_update_failed else '✅ Нижняя WebApp-кнопка обновлена.\n'}"
        "✅ Свежая reply-клавиатура отправлена ниже.\n"
        "WebApp открывается через обе кнопки «🎰 Запустить кампанию».",
        reply_markup=await get_active_main_menu_keyboard(
            kwargs.get("lang", "ru"),
            user_id=message.from_user.id,
        ),
    )
    _log_admin_action(message.from_user.id, f"webapp_url: {webapp_url_value}")


@router.message(Command("refresh_menu"))
async def refresh_menu(message: Message, bot: Bot, **kwargs: Any) -> None:
    """Принудительно обновить reply-меню у всех пользователей."""
    if not await _is_admin(message.from_user.id):
        return

    db = await get_db()
    async with db.execute("SELECT id, language_code FROM users") as cursor:
        users = await cursor.fetchall()

    total = len(users)
    await message.answer(f"🔄 Обновляю меню у пользователей: <b>{total}</b>")

    sent = 0
    failed = 0
    blocked = 0
    menu_updated = 0
    webapp_url_value = await get_active_webapp_url()

    for idx, user in enumerate(users, 1):
        user_id = int(user["id"])
        lang = user["language_code"] or "ru"
        menu_button = MenuButtonWebApp(
            text="🎰 Запустить кампанию",
            web_app=WebAppInfo(url=build_webapp_launch_url(webapp_url_value, user_id)),
        )

        try:
            await bot.set_chat_menu_button(chat_id=user_id, menu_button=menu_button)
            menu_updated += 1
            await bot.send_message(
                chat_id=user_id,
                text="📱",
                reply_markup=await get_active_main_menu_keyboard(lang, user_id=user_id),
                disable_notification=True,
            )
            sent += 1
        except TelegramForbiddenError:
            blocked += 1
            failed += 1
            await set_user_blocked(user_id, blocked=True)
        except (TelegramBadRequest, TelegramNotFound):
            failed += 1
        except Exception as exc:
            failed += 1
            logger.warning("refresh_menu: user=%d send failed: %s", user_id, exc)

        # Бережём лимиты Telegram API.
        if idx % 25 == 0:
            await asyncio.sleep(1)

    await message.answer(
        "✅ Обновление меню завершено.\n"
        f"Отправлено: <b>{sent}</b>\n"
        f"Нижняя WebApp-кнопка обновлена: <b>{menu_updated}</b>\n"
        f"Ошибок: <b>{failed}</b>\n"
        f"Заблокировали бота: <b>{blocked}</b>"
    )

    _log_admin_action(
        message.from_user.id,
        f"refresh_menu: total={total}, sent={sent}, menu_updated={menu_updated}, failed={failed}, blocked={blocked}",
    )


@router.message(Command("send"))
async def send_cmd(
    message: Message,
    state: FSMContext,
    **kwargs: Any,
) -> None:
    """Начать процесс рассылки: запросить сообщение или сразу спросить про кнопку."""
    if not await _is_admin(message.from_user.id):
        return

    send_text, send_entities, photo_file_id = _extract_send_payload(message)
    
    if not send_text.strip() and not photo_file_id:
        await state.set_state(AdminSendState.waiting_message)
        await message.answer(
            "Отправьте сообщение (текст или фото с подписью), которое нужно разослать всем участникам.\n"
            "Для отмены используйте /cancel."
        )
        return

    if len(send_text) > 4096:
        await message.answer("❌ Сообщение слишком длинное. Максимум: 4096 символов.")
        return

    await _proceed_to_button_choice(message, state, send_text, send_entities, photo_file_id)

@router.message(AdminSendState.waiting_message, Command("cancel"))
async def send_cancel_wait(message: Message, state: FSMContext, **kwargs: Any) -> None:
    if not await _is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer("❌ Рассылка отменена.")

@router.message(AdminSendState.waiting_message)
async def send_message_received(message: Message, state: FSMContext, **kwargs: Any) -> None:
    if not await _is_admin(message.from_user.id):
        return
    
    text = message.text or message.caption or ""
    photo_file_id = message.photo[-1].file_id if message.photo else None
    entities = message.entities or message.caption_entities or []
    
    if not text.strip() and not photo_file_id:
        await message.answer("Пожалуйста, отправьте текст или фото. Для отмены используйте /cancel.")
        return
        
    await _proceed_to_button_choice(message, state, text, entities, photo_file_id)

async def _proceed_to_button_choice(
    message: Message, 
    state: FSMContext, 
    send_text: str, 
    send_entities: list[MessageEntity], 
    photo_file_id: str | None
) -> None:
    await state.set_state(AdminSendState.waiting_button_choice)
    await state.update_data(
        send_text=send_text,
        send_entities=[entity.model_dump(mode="json") for entity in send_entities],
        photo_file_id=photo_file_id
    )
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить кнопку", callback_data="btn_add")],
        [InlineKeyboardButton(text="⏭ Без кнопки", callback_data="btn_skip")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="btn_cancel")],
    ])
    await message.answer("Хотите добавить инлайн-кнопку со ссылкой на старт бота?", reply_markup=markup)

@router.callback_query(AdminSendState.waiting_button_choice, F.data == "btn_cancel")
async def btn_cancel_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Рассылка отменена.")
    await callback.answer()

@router.callback_query(AdminSendState.waiting_button_choice, F.data == "btn_skip")
async def btn_skip_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await _show_send_preview(callback.message, state, None)

@router.callback_query(AdminSendState.waiting_button_choice, F.data == "btn_add")
async def btn_add_callback(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminSendState.waiting_button_text)
    await callback.message.edit_text("✏️ Введите текст для инлайн-кнопки (например, \"Забрать PS5\"):")
    await callback.answer()

@router.message(AdminSendState.waiting_button_text, Command("cancel"))
async def btn_text_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Рассылка отменена.")

@router.message(AdminSendState.waiting_button_text)
async def btn_text_received(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        return
    await _show_send_preview(message, state, text)

async def _show_send_preview(message: Message, state: FSMContext, button_text: str | None):
    data = await state.get_data()
    send_text = data.get("send_text") or ""
    raw_entities = data.get("send_entities") or []
    send_entities = [MessageEntity(**item) for item in raw_entities]
    photo_file_id = data.get("photo_file_id")
    
    if button_text:
        await state.update_data(button_text=button_text)

    await state.set_state(AdminSendState.waiting_confirm)
    
    kb_preview = None
    if button_text:
        bot_link = f"https://t.me/{config.BOT_USERNAME}?start=broadcast"
        kb_preview = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=button_text, url=bot_link)],
            [
                InlineKeyboardButton(text="✅ Отправить", callback_data=_SEND_CONFIRM_DATA),
                InlineKeyboardButton(text="❌ Отмена", callback_data=_SEND_CANCEL_DATA),
            ]
        ])
    else:
        kb_preview = _get_send_preview_keyboard()

    await message.answer("📣 <b>Предпросмотр рассылки</b>")
    if photo_file_id:
        await message.answer_photo(
            photo=photo_file_id,
            caption=send_text,
            caption_entities=send_entities,
            reply_markup=kb_preview
        )
    else:
        await message.answer(
            send_text,
            entities=send_entities,
            parse_mode=None,
            reply_markup=kb_preview
        )
    
    _log_admin_action(message.from_user.id, f"send_preview: len={len(send_text)}")


@router.callback_query(F.data == _SEND_CANCEL_DATA)
async def send_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    **kwargs: Any,
) -> None:
    """Отменить подготовленную админ-рассылку /send."""
    if not await _is_admin(callback.from_user.id):
        await callback.answer()
        return

    await state.clear()
    await callback.answer()

    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.message.answer("❌ Рассылка отменена.")

    _log_admin_action(callback.from_user.id, "send_cancel")


@router.callback_query(F.data == _SEND_CONFIRM_DATA)
async def send_confirm(
    callback: CallbackQuery,
    bot: Bot,
    state: FSMContext,
    **kwargs: Any,
) -> None:
    """Подтвердить и выполнить админ-рассылку /send по всем записям users."""
    if not await _is_admin(callback.from_user.id):
        await callback.answer()
        return

    current_state = await state.get_state()
    data = await state.get_data()
    send_text = data.get("send_text") or ""
    raw_entities = data.get("send_entities") or []
    send_entities = [MessageEntity(**item) for item in raw_entities]
    photo_file_id = data.get("photo_file_id")
    button_text = data.get("button_text")

    if current_state != AdminSendState.waiting_confirm.state or (not send_text.strip() and not photo_file_id):
        await callback.answer("⚠️ Нет активной рассылки для подтверждения.", show_alert=True)
        await state.clear()
        return

    await callback.answer("🚀 Рассылка запущена")
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    reply_markup = None
    if button_text:
        bot_link = f"https://t.me/{config.BOT_USERNAME}?start=broadcast"
        reply_markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=button_text, url=bot_link)]])

    db = await get_db()
    async with db.execute("SELECT id FROM users") as cursor:
        users = await cursor.fetchall()

    total = len(users)
    if callback.message:
        await callback.message.answer(f"🔄 Начинаю рассылку: <b>{total}</b> пользователей")

    sent = 0
    failed = 0
    blocked = 0

    for idx, user in enumerate(users, 1):
        user_id = int(user["id"])

        try:
            if photo_file_id:
                await bot.send_photo(
                    chat_id=user_id,
                    photo=photo_file_id,
                    caption=send_text,
                    caption_entities=send_entities,
                    reply_markup=reply_markup
                )
            else:
                await bot.send_message(
                    chat_id=user_id,
                    text=send_text,
                    entities=send_entities,
                    parse_mode=None,
                    reply_markup=reply_markup
                )
            sent += 1
        except TelegramForbiddenError:
            blocked += 1
            failed += 1
            await set_user_blocked(user_id, blocked=True)
        except (TelegramBadRequest, TelegramNotFound):
            failed += 1
        except Exception as exc:
            failed += 1
            logger.warning("send_broadcast: user=%d send failed: %s", user_id, exc)

        # Бережём лимиты Telegram API.
        if idx % 25 == 0:
            await asyncio.sleep(1)

    await state.clear()

    summary = (
        "✅ Рассылка завершена.\n"
        f"Всего в базе: <b>{total}</b>\n"
        f"Отправлено: <b>{sent}</b>\n"
        f"Ошибок: <b>{failed}</b>\n"
        f"Заблокировали бота: <b>{blocked}</b>"
    )

    if callback.message:
        await callback.message.answer(summary)

    _log_admin_action(
        callback.from_user.id,
        f"send_confirm: total={total}, sent={sent}, failed={failed}, blocked={blocked}",
    )


@router.message(Command("draw"))
async def trigger_draw(message: Message, bot: Bot, **kwargs: Any) -> None:
    """Запустить розыгрыш (только для админов)."""
    if not await _is_admin(message.from_user.id):
        return

    from utils.draw import DrawPrizesNotConfiguredError, perform_draw

    await message.answer("🎲 Запуск розыгрыша...")
    _log_admin_action(message.from_user.id, "draw_started")

    try:
        winners = await perform_draw(bot)

        if not winners:
            await message.answer(
                "❌ Розыгрыш не удался: недостаточно eligible участников для текущего списка призов."
            )
            return

        lines = ["🏆 <b>Результаты розыгрыша:</b>\n"]
        for idx, w in enumerate(winners, 1):
            name = escape(str(w.get("username") or w.get("first_name") or w["user_id"]))
            if w.get("username"):
                name = f"@{name}"
            lines.append(f"{idx}. {name} — <b>{escape(str(w['prize']))}</b>")

        await message.answer("\n".join(lines))
        _log_admin_action(message.from_user.id, f"draw_completed: {len(winners)} winners")

    except DrawPrizesNotConfiguredError:
        await message.answer(
            "❌ Призы конкурса не настроены.\n"
            "Сначала задайте список через /set_prizes, затем повторите /draw."
        )
        _log_admin_action(message.from_user.id, "draw_error: prizes_not_configured")
    except Exception as e:
        logger.error("Ошибка розыгрыша: %s", e)
        await message.answer(f"❌ Ошибка: {e}")
        _log_admin_action(message.from_user.id, f"draw_error: {e}")
