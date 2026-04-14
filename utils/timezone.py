"""
Вспомогательные функции для расчёта суток в часовом поясе Europe/Kiev.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from config import TIMEZONE

_KYIV_TZ = ZoneInfo(TIMEZONE)


def get_kyiv_day_bounds_utc(now: datetime | None = None) -> tuple[datetime, datetime]:
    """
    Вернуть границы текущих киевских суток в UTC: [start, end).

    Args:
        now: опциональная точка времени. Если naive, трактуется как UTC.
    """
    if now is None:
        now_kyiv = datetime.now(_KYIV_TZ)
    else:
        now_aware = now.replace(tzinfo=UTC) if now.tzinfo is None else now
        now_kyiv = now_aware.astimezone(_KYIV_TZ)

    day_start_kyiv = datetime.combine(now_kyiv.date(), time.min, tzinfo=_KYIV_TZ)
    day_end_kyiv = day_start_kyiv + timedelta(days=1)

    return day_start_kyiv.astimezone(UTC), day_end_kyiv.astimezone(UTC)


def to_sqlite_utc(dt: datetime) -> str:
    """Преобразовать datetime в формат SQLite UTC YYYY-MM-DD HH:MM:SS."""
    dt_aware = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return dt_aware.strftime("%Y-%m-%d %H:%M:%S")
