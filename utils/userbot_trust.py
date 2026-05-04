"""Hidden userbot trust scoring via Telegram common groups."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import config
from db.models import (
    TRUST_STATUS_DISABLED,
    TRUST_STATUS_ERROR,
    TRUST_STATUS_UNRESOLVABLE,
    calculate_trust_multiplier,
    set_user_trust_score,
)

logger = logging.getLogger(__name__)

_LOCK = asyncio.Lock()


@dataclass(frozen=True)
class TrustCheckResult:
    user_id: int
    common_chat_count: int
    draw_multiplier: float
    status: str
    error: Optional[str] = None


def _is_configured() -> bool:
    return bool(config.TELEGRAM_API_ID and config.TELEGRAM_API_HASH)


async def check_common_groups_with_userbot(
    user_id: int,
    username: Optional[str] = None,
) -> TrustCheckResult:
    """Check hidden common group count with the configured Telethon userbot."""
    if not _is_configured():
        return TrustCheckResult(
            user_id=user_id,
            common_chat_count=0,
            draw_multiplier=1.0,
            status=TRUST_STATUS_DISABLED,
            error="userbot_not_configured",
        )

    try:
        from telethon import TelegramClient
        from telethon.tl.functions.messages import GetCommonChatsRequest
    except Exception as exc:
        return TrustCheckResult(
            user_id=user_id,
            common_chat_count=0,
            draw_multiplier=1.0,
            status=TRUST_STATUS_DISABLED,
            error=f"telethon_unavailable: {exc}",
        )

    async with _LOCK:
        client = TelegramClient(
            str(config.USERBOT_SESSION_PATH),
            int(config.TELEGRAM_API_ID),
            str(config.TELEGRAM_API_HASH),
        )
        try:
            await client.connect()
            if not await client.is_user_authorized():
                return TrustCheckResult(
                    user_id=user_id,
                    common_chat_count=0,
                    draw_multiplier=1.0,
                    status=TRUST_STATUS_DISABLED,
                    error="userbot_session_not_authorized",
                )

            entity_ref: int | str = username if username else int(user_id)
            try:
                entity = await client.get_entity(entity_ref)
            except Exception as exc:
                return TrustCheckResult(
                    user_id=user_id,
                    common_chat_count=0,
                    draw_multiplier=1.0,
                    status=TRUST_STATUS_UNRESOLVABLE,
                    error=f"entity_unresolvable: {exc}",
                )

            result = await client(
                GetCommonChatsRequest(user_id=entity, max_id=0, limit=100)
            )
            common_chat_count = len(getattr(result, "chats", []) or [])
            return TrustCheckResult(
                user_id=user_id,
                common_chat_count=common_chat_count,
                draw_multiplier=calculate_trust_multiplier(common_chat_count),
                status="boosted" if common_chat_count >= 1 else "plain",
            )
        except Exception as exc:
            logger.warning("userbot trust check failed for user=%d: %s", user_id, exc)
            return TrustCheckResult(
                user_id=user_id,
                common_chat_count=0,
                draw_multiplier=1.0,
                status=TRUST_STATUS_ERROR,
                error=str(exc),
            )
        finally:
            await client.disconnect()


async def refresh_user_trust_score(user_id: int, username: Optional[str] = None) -> TrustCheckResult:
    """Run hidden trust check and persist the x1/x5 draw multiplier."""
    result = await check_common_groups_with_userbot(user_id, username=username)
    await set_user_trust_score(
        user_id=user_id,
        common_chat_count=result.common_chat_count,
        status=result.status,
        error=result.error,
    )
    logger.info(
        "Hidden trust score refreshed: user=%d status=%s common=%d multiplier=%.1f",
        user_id,
        result.status,
        result.common_chat_count,
        result.draw_multiplier,
    )
    return result
