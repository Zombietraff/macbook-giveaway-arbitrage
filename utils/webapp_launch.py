"""Signed launch-token fallback for Telegram WebApp entry points."""

from __future__ import annotations

import base64
import hmac
import time
from hashlib import sha256
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from config import BOT_TOKEN

_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 60


def _sign(payload: str) -> str:
    return hmac.new(BOT_TOKEN.encode(), payload.encode(), sha256).hexdigest()


def create_webapp_launch_token(user_id: int) -> str:
    """Create a signed token that can identify one user for WebApp API auth."""
    expires_at = int(time.time()) + _TOKEN_TTL_SECONDS
    payload = f"{int(user_id)}:{expires_at}"
    encoded_payload = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    return f"{encoded_payload}.{_sign(payload)}"


def validate_webapp_launch_token(token: str) -> dict | None:
    """Validate a signed WebApp launch token and return Telegram-like user data."""
    try:
        encoded_payload, signature = token.split(".", maxsplit=1)
        padded_payload = encoded_payload + "=" * (-len(encoded_payload) % 4)
        payload = base64.urlsafe_b64decode(padded_payload.encode()).decode()
        user_id_raw, expires_at_raw = payload.split(":", maxsplit=1)

        if not hmac.compare_digest(signature, _sign(payload)):
            return None
        if int(expires_at_raw) < int(time.time()):
            return None

        return {"id": int(user_id_raw)}
    except Exception:
        return None


def build_webapp_launch_url(webapp_url: str, user_id: int | None) -> str:
    """Attach a signed launch token to a WebApp URL for user-specific buttons."""
    if user_id is None:
        return webapp_url

    parts = urlsplit(webapp_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["launch"] = create_webapp_launch_token(user_id)
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        )
    )
