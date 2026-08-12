"""Verifying who a Mini App submission came from.

The page runs on the user's phone, so everything it sends us is untrusted —
including the identity it claims. Telegram signs the launch parameters with a
key derived from the bot token, and checking that signature is the only thing
that makes a POST from the page as trustworthy as a message arriving through
the bot itself. Without it, anyone who found the URL could post hours into
someone else's month.

https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
from urllib.parse import parse_qsl

# The app can sit open on a phone for a while before the user saves, so the
# window is generous — but not unlimited: a signature that still worked days
# later would be a replay window for anyone who captured one.
MAX_AGE = dt.timedelta(hours=24)


class InitDataError(Exception):
    """Launch parameters that were missing, malformed, stale or unsigned."""


def _hash_over(fields: dict[str, str], secret: bytes) -> str:
    check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    return hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()


def verify_init_data(
    raw: str,
    bot_token: str,
    now: dt.datetime | None = None,
    max_age: dt.timedelta = MAX_AGE,
) -> int:
    """Return the Telegram user id carried by ``raw``, or raise InitDataError."""
    if not raw:
        raise InitDataError("no launch parameters")

    try:
        fields = dict(parse_qsl(raw, strict_parsing=True, keep_blank_values=True))
    except ValueError:
        raise InitDataError("launch parameters are not a query string")

    received = fields.pop("hash", "")
    if not received:
        raise InitDataError("launch parameters carry no signature")

    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()

    # Newer clients add an Ed25519 "signature" field for third-party validation.
    # Whether it belongs in the hashed string has varied, and getting it wrong
    # rejects every real submission, so both readings are accepted — the token
    # still has to be known either way, which is what the check is actually for.
    candidates = [_hash_over(fields, secret)]
    if "signature" in fields:
        without = {k: v for k, v in fields.items() if k != "signature"}
        candidates.append(_hash_over(without, secret))
    if not any(hmac.compare_digest(c, received) for c in candidates):
        raise InitDataError("signature does not match")

    try:
        signed_at = dt.datetime.fromtimestamp(int(fields["auth_date"]), dt.timezone.utc)
    except (KeyError, ValueError, OverflowError, OSError):
        raise InitDataError("launch parameters carry no usable auth_date")

    now = now or dt.datetime.now(dt.timezone.utc)
    # Both directions: a timestamp in the future is as much a sign of a forged
    # or replayed launch as one long past.
    if not (-max_age <= now - signed_at <= max_age):
        raise InitDataError("launch parameters are stale")

    try:
        user = json.loads(fields["user"])
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError):
        raise InitDataError("launch parameters name no user")

    return user_id
