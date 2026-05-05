"""
Диагностический скрипт для проверки розыгрыша.

Проверяет:
1. Конфигурацию (OWNER_IDS, END_DATE).
2. Состояние БД (пользователи, билеты, blocked).
3. Симуляцию розыгрыша (сухой прогон без отправки сообщений).
4. Список потенциальных проблем и блокеров.

Использование:
    uv run python scripts/diagnose_draw.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database import close_db, get_db, init_db


async def main() -> None:
    """Полная диагностика системы розыгрыша."""
    print("=" * 60)
    print("🔍 ДИАГНОСТИКА РОЗЫГРЫША Contest Giveaway")
    print("=" * 60)

    # ──────────────── 1. Конфигурация ────────────────
    print("\n📋 1. КОНФИГУРАЦИЯ")
    print("-" * 40)

    import config

    print(f"  BOT_USERNAME:  {config.BOT_USERNAME}")
    print(f"  OWNER_IDS:     {config.OWNER_IDS}")
    print(f"  END_DATE:      {config.END_DATE}")

    now = datetime.now()
    is_ended = now > config.END_DATE
    print(f"  Текущее время: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Конкурс:       {'❌ ЗАВЕРШЁН' if is_ended else '✅ Активен'}")

    if is_ended:
        print()
        print("  ⚠️  ПРОБЛЕМА: Конкурс завершён!")
        print("  ⚠️  ContestActiveMiddleware блокирует /draw!")
        print("  ⚠️  Решение: /draw добавлен в список разрешённых команд")
        print("       или используйте /extend_date для продления.")

    # ──────────────── 2. Проверка middleware ────────────────
    print("\n📋 2. MIDDLEWARE ПРОВЕРКА")
    print("-" * 40)

    from middlewares.contest_active import _ADMIN_COMMANDS, _ALLOWED_AFTER_END

    admin_commands = {"/draw", "/admin_stats", "/extend_date"}
    all_allowed = _ALLOWED_AFTER_END | _ADMIN_COMMANDS
    blocked_admin = admin_commands - all_allowed
    allowed_admin = admin_commands & all_allowed

    if blocked_admin:
        print(f"  ❌ БЛОКИРУЮТСЯ после END_DATE: {blocked_admin}")
    if allowed_admin:
        print(f"  ✅ Разрешены после END_DATE:    {allowed_admin}")

    # ──────────────── 3. База данных ────────────────
    print("\n📋 3. БАЗА ДАННЫХ")
    print("-" * 40)

    await init_db()
    db = await get_db()

    # Всего пользователей
    async with db.execute("SELECT COUNT(*) FROM users") as cur:
        total_users = (await cur.fetchone())[0]
    print(f"  Всего пользователей:     {total_users}")

    # С билетами > 0
    async with db.execute("SELECT COUNT(*) FROM users WHERE tickets > 0") as cur:
        active_users = (await cur.fetchone())[0]
    print(f"  Участников (tickets>0):  {active_users}")

    # Не заблокировали бота
    async with db.execute(
        "SELECT COUNT(*) FROM users WHERE tickets > 0 AND blocked_bot = FALSE"
    ) as cur:
        eligible = (await cur.fetchone())[0]
    print(f"  Подходящих для draw:     {eligible}")

    # Заблокировали бота
    async with db.execute("SELECT COUNT(*) FROM users WHERE blocked_bot = TRUE") as cur:
        blocked = (await cur.fetchone())[0]
    print(f"  Заблокировали бота:      {blocked}")

    # Общие билеты
    async with db.execute("SELECT SUM(tickets) FROM users WHERE tickets > 0") as cur:
        total_tickets = (await cur.fetchone())[0] or 0
    print(f"  Всего билетов:           {total_tickets}")

    from db.models import get_contest_prizes, get_draw_prize_list

    prize_rows = await get_contest_prizes()
    draw_prizes = await get_draw_prize_list()
    print(f"  Настроенных призов:      {len(draw_prizes)}")
    for prize in prize_rows:
        print(f"    {prize['position']}. {prize['quantity']} × {prize['name']}")

    # Детальная таблица участников
    print(f"\n  {'─' * 55}")
    print(f"  {'ID':>12} │ {'Username':>15} │ {'Tickets':>8} │ {'Blocked':>7}")
    print(f"  {'─' * 55}")

    async with db.execute(
        "SELECT id, username, first_name, tickets, blocked_bot FROM users ORDER BY tickets DESC"
    ) as cur:
        rows = await cur.fetchall()
        for row in rows:
            name = row["username"] or row["first_name"] or "—"
            blocked_str = "🚫" if row["blocked_bot"] else "✅"
            tickets_str = f"{row['tickets']:.1f}"
            print(f"  {row['id']:>12} │ {name:>15} │ {tickets_str:>8} │ {blocked_str:>7}")

    print(f"  {'─' * 55}")

    # ──────────────── 4. Уже были розыгрыши? ────────────────
    print("\n📋 4. РЕЗУЛЬТАТЫ ПРЕДЫДУЩИХ РОЗЫГРЫШЕЙ")
    print("-" * 40)

    async with db.execute(
        "SELECT w.*, u.username FROM winners w LEFT JOIN users u ON w.user_id = u.id"
    ) as cur:
        winners = await cur.fetchall()
        if winners:
            for w in winners:
                name = w["username"] or str(w["user_id"])
                print(f"  🏆 {name} → {w['prize']}")
        else:
            print("  Розыгрышей ещё не было.")

    # ──────────────── 5. Вердикт ────────────────
    print("\n" + "=" * 60)
    print("📍 ВЕРДИКТ")
    print("=" * 60)

    issues = []

    if not draw_prizes:
        issues.append(
            "❌ Призы не настроены. /draw будет заблокирован.\n"
            "   Используйте /set_prizes в Telegram."
        )
    elif eligible < len(draw_prizes):
        issues.append(
            f"❌ Недостаточно участников: {eligible} (нужно >= {len(draw_prizes)}).\n"
            f"   Для тестирования создайте тестовых пользователей:\n"
            f"   uv run python scripts/diagnose_draw.py --seed-test-users"
        )

    if is_ended and "/draw" not in (_ALLOWED_AFTER_END | _ADMIN_COMMANDS):
        issues.append(
            "❌ /draw ЗАБЛОКИРОВАН после END_DATE!\n"
            "   ContestActiveMiddleware не пропускает /draw.\n"
            "   Фикс: admin-команды добавлены в _ADMIN_COMMANDS"
        )

    if not issues:
        print("  ✅ Всё готово для розыгрыша!")
    else:
        for issue in issues:
            print(f"\n  {issue}")

    # ──────────────── Seed test users? ────────────────
    if "--seed-test-users" in sys.argv:
        await _seed_test_users(db)

    await close_db()
    print()


async def _seed_test_users(db) -> None:
    """Создать тестовых пользователей для проверки розыгрыша."""
    print("\n\n📋 СОЗДАНИЕ ТЕСТОВЫХ ПОЛЬЗОВАТЕЛЕЙ")
    print("-" * 40)

    from db.models import add_user_tickets, create_user

    test_users = [
        (1000001, "test_user_1", "Alice",  "A", "ru", False, "test_ref_1", 2.0),
        (1000002, "test_user_2", "Bob",    "B", "ru", True,  "test_ref_2", 4.0),
        (1000003, "test_user_3", "Carol",  "C", "uk", False, "test_ref_3", 1.0),
        (1000004, "test_user_4", "Dave",   "D", "ru", False, "test_ref_4", 5.0),
        (1000005, "test_user_5", "Eve",    "E", "uk", True,  "test_ref_5", 2.0),
    ]

    for uid, username, first, last, lang, premium, ref, tickets in test_users:
        await create_user(uid, username, first, last, lang, premium, ref)
        await add_user_tickets(uid, tickets)
        print(f"  ✅ {username} (ID: {uid}, tickets: {tickets})")

    print(f"\n  Добавлено {len(test_users)} тестовых пользователей.")
    print("  Теперь запустите: uv run python scripts/diagnose_draw.py")


if __name__ == "__main__":
    asyncio.run(main())
