"""Verifying the launch parameters Telegram signs.

This is the only thing standing between the public POST endpoint and anyone
who knows the URL, so the tests are about what must be *refused* as much as
what must be accepted.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest

from salary_bot.core import webauth

TOKEN = "123456:AAH-fake-token-for-tests"
NOW = dt.datetime(2026, 6, 10, 12, 0, tzinfo=dt.timezone.utc)


def sign(fields: dict[str, str], token: str = TOKEN) -> str:
    """Build an initData string the way a Telegram client would."""
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": signature})


def launch(user_id: int = 111, at: dt.datetime = NOW, token: str = TOKEN, **extra) -> str:
    return sign({
        "auth_date": str(int(at.timestamp())),
        "query_id": "AAF_test",
        "user": json.dumps({"id": user_id, "first_name": "Test"}),
        **extra,
    }, token)


def test_a_signed_launch_yields_its_user():
    assert webauth.verify_init_data(launch(user_id=777), TOKEN, now=NOW) == 777


def test_a_launch_signed_with_another_token_is_refused():
    """The whole point: only someone holding the bot token can produce one."""
    forged = launch()
    with pytest.raises(webauth.InitDataError):
        webauth.verify_init_data(forged, "999:different-token", now=NOW)


def test_tampering_with_the_user_breaks_the_signature():
    """Posting hours into someone else's month is the attack this stops."""
    raw = launch(user_id=111)
    tampered = raw.replace(
        urlencode({"user": json.dumps({"id": 111, "first_name": "Test"})}),
        urlencode({"user": json.dumps({"id": 222, "first_name": "Test"})}),
    )
    assert tampered != raw, "the substitution must actually have happened"
    with pytest.raises(webauth.InitDataError):
        webauth.verify_init_data(tampered, TOKEN, now=NOW)


@pytest.mark.parametrize("raw", [
    "",
    "not a query string at all",
    "auth_date=1&user=%7B%7D",                      # no hash
    "auth_date=1&user=%7B%7D&hash=deadbeef",        # wrong hash
])
def test_malformed_launches_are_refused(raw):
    with pytest.raises(webauth.InitDataError):
        webauth.verify_init_data(raw, TOKEN, now=NOW)


def test_a_stale_launch_is_refused():
    """A captured launch must not stay usable for days."""
    old = launch(at=NOW - dt.timedelta(hours=25))
    with pytest.raises(webauth.InitDataError):
        webauth.verify_init_data(old, TOKEN, now=NOW)


def test_a_launch_from_the_future_is_refused():
    ahead = launch(at=NOW + dt.timedelta(hours=25))
    with pytest.raises(webauth.InitDataError):
        webauth.verify_init_data(ahead, TOKEN, now=NOW)


def test_a_launch_still_inside_the_window_is_accepted():
    """The app can sit open on a phone for hours before the user saves."""
    recent = launch(at=NOW - dt.timedelta(hours=23))
    assert webauth.verify_init_data(recent, TOKEN, now=NOW) == 111


def test_a_launch_naming_no_user_is_refused():
    raw = sign({"auth_date": str(int(NOW.timestamp())), "query_id": "AAF"})
    with pytest.raises(webauth.InitDataError):
        webauth.verify_init_data(raw, TOKEN, now=NOW)


def test_the_ed25519_signature_field_does_not_break_verification():
    """Newer clients add it; it must not turn every real launch into a reject,
    whichever side of the hashed string it falls on."""
    fields = {
        "auth_date": str(int(NOW.timestamp())),
        "user": json.dumps({"id": 111, "first_name": "Test"}),
        "signature": "ed25519-blob",
    }
    # Signed with the field included...
    assert webauth.verify_init_data(sign(fields), TOKEN, now=NOW) == 111

    # ...and signed with it excluded, which is the other documented reading.
    without = {k: v for k, v in fields.items() if k != "signature"}
    check = "\n".join(f"{k}={without[k]}" for k in sorted(without))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    raw = urlencode({
        **fields,
        "hash": hmac.new(secret, check.encode(), hashlib.sha256).hexdigest(),
    })
    assert webauth.verify_init_data(raw, TOKEN, now=NOW) == 111
