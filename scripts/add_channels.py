"""
Скрипт для добавления каналов обязательной подписки в БД.

Использование:
    # Интерактивный режим:
    uv run python scripts/add_channels.py

    # Прямое добавление:
    uv run python scripts/add_channels.py --id "-1001234567890" --title "Канал 1" --link "https://t.me/channel1"

    # Показать текущие каналы:
    uv run python scripts/add_channels.py --list

    # Удалить канал:
    uv run python scripts/add_channels.py --remove "-1001234567890"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Добавляем корень проекта в sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database import close_db, get_db, init_db
from db.models import add_channel, get_all_channels, update_channel


async def list_channels() -> None:
    """Показать все каналы в БД."""
    channels = await get_all_channels()
    if not channels:
        print("📭 Нет каналов в БД.")
        return

    print(f"\n📢 Каналы ({len(channels)}):\n")
    for ch in channels:
        print(f"  ID: {ch['channel_id']}")
        print(f"  Название: {ch['title']}")
        print(f"  Ссылка: {ch['invite_link']}")
        print()


async def remove_channel(channel_id: str) -> None:
    """Удалить канал из БД."""
    db = await get_db()
    await db.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
    await db.commit()
    print(f"✅ Канал {channel_id} удалён.")


async def edit_channel(channel_id: str, title: str, invite_link: str) -> None:
    """Обновить канал в БД."""
    await update_channel(channel_id, title, invite_link)
    print(f"✅ Канал {channel_id} ('{title}') успешно обновлён!")


async def add_channel_interactive() -> None:
    """Интерактивное добавление каналов."""
    print("\n📢 Добавление канала обязательной подписки")
    print("=" * 45)
    print()

    while True:
        channel_id = input("Channel ID (например -1001234567890, или 'q' для выхода): ").strip()
        if channel_id.lower() == 'q':
            break

        title = input("Название канала: ").strip()
        invite_link = input("Ссылка (https://t.me/...): ").strip()

        if not all([channel_id, title, invite_link]):
            print("❌ Все поля обязательны!\n")
            continue

        await add_channel(channel_id, title, invite_link)
        print(f"✅ Канал '{title}' добавлен!\n")

        more = input("Добавить ещё канал? (y/n): ").strip().lower()
        if more != 'y':
            break


async def main() -> None:
    parser = argparse.ArgumentParser(description="Управление каналами для подписки")
    parser.add_argument("--list", action="store_true", help="Показать все каналы")
    parser.add_argument("--id", type=str, help="Channel ID для добавления/обновления")
    parser.add_argument("--title", type=str, help="Название канала")
    parser.add_argument("--link", type=str, help="Ссылка на канал")
    parser.add_argument("--remove", type=str, help="Channel ID для удаления")
    parser.add_argument("--update", action="store_true", help="Обновить существующий канал вместо добавления")

    args = parser.parse_args()

    await init_db()

    try:
        if args.list:
            await list_channels()
        elif args.remove:
            await remove_channel(args.remove)
        elif args.id and args.title and args.link:
            if args.update:
                await edit_channel(args.id, args.title, args.link)
            else:
                await add_channel(args.id, args.title, args.link)
                print(f"✅ Канал '{args.title}' добавлен!")
        else:
            # Интерактивный режим
            await list_channels()
            await add_channel_interactive()
            print("\n--- Текущие каналы ---")
            await list_channels()
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
