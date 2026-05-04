"""Authorize the Telethon userbot session used for hidden trust checks."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config


async def main() -> None:
    if not config.TELEGRAM_API_ID or not config.TELEGRAM_API_HASH:
        raise SystemExit("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env first.")

    try:
        from telethon import TelegramClient
    except Exception as exc:
        raise SystemExit(f"Telethon is not installed: {exc}") from exc

    client = TelegramClient(
        str(config.USERBOT_SESSION_PATH),
        int(config.TELEGRAM_API_ID),
        str(config.TELEGRAM_API_HASH),
    )
    await client.start()
    me = await client.get_me()
    print(f"Userbot session authorized: id={me.id} username={getattr(me, 'username', None)}")
    print(f"Session path: {config.USERBOT_SESSION_PATH}")
    await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
