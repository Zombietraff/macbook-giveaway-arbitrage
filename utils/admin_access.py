"""Role-based access helpers for owner and temporary admins."""

from __future__ import annotations

import config
from db.models import is_active_temporary_admin


def is_owner(user_id: int | None) -> bool:
    """Owner IDs are configured through OWNER_IDS in .env."""
    return bool(user_id) and int(user_id) in config.OWNER_IDS


async def is_temp_admin(user_id: int | None) -> bool:
    """Temporary admins are stored in DB and can be revoked by owners."""
    return bool(user_id) and await is_active_temporary_admin(int(user_id))


async def is_admin(user_id: int | None) -> bool:
    """Any admin role: owner or active temporary admin."""
    return is_owner(user_id) or await is_temp_admin(user_id)


def can_manage_system(user_id: int | None) -> bool:
    """System settings are owner-only."""
    return is_owner(user_id)


async def can_manage_contest(user_id: int | None) -> bool:
    """Contest operations are available to owners and temporary admins."""
    return await is_admin(user_id)
