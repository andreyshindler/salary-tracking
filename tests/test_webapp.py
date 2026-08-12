"""The Mini App: the served page, the payload it returns, and the fallback.

The payload is JSON built by a page running on the user's phone, so it is
treated as untrusted input and validated rather than believed.
"""
from __future__ import annotations

import datetime as dt
import json
import re

import pytest

from salary_bot.bot import webserver
from salary_bot.bot.handlers import calendar as cal_handlers
from salary_bot.bot.handlers import common
from salary_bot.bot.handlers import webapp
from salary_bot.core import db, repo
from tests.conftest import NIGHT_RATE, RATE
from tests.stubs import TG_ID, FakeContext, FakeUpdate, callback_data, last_output

WEBAPP_URL = "https://bot.example.com"


def _config(tmp_path, url: str = ""):
    from salary_bot.config import Config

    return Config(
        bot_token="123:FAKE",
        allowed_user_ids=frozenset({TG_ID}),
        db_path=tmp_path / "bot.db",
        log_level="INFO",
        webapp_url=url,
    )


@pytest.fixture()
def bot_env(tmp_path):
    """Mini App disabled — the default, and the fallback path."""
    db.init_engine(f"sqlite:///{tmp_path/'bot.db'}")
    common.set_config(_config(tmp_path))
    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        repo.set_rate(s, user.id, RATE, dt.date(2000, 1, 1), NIGHT_RATE)
    return tmp_path


@pytest.fixture()
def webapp_env(bot_env):
    """Mini App enabled."""
    common.set_config(_config(bot_env, WEBAPP_URL))
    return bot_env


@pytest.fixture()
def ctx():
    return FakeContext()


# ------------------------------------------------------------------ the page

@pytest.mark.asyncio
async def test_the_page_is_served(aiohttp_client):
    client = await aiohttp_client(webserver.build_app())
    response = await client.get("/")
    assert response.status == 200

    body = await response.text()
    assert "telegram-web-app.js" in body, "the Telegram bridge must be loaded"
    assert 'dir="rtl"' in body
    assert "scroll-snap-type" in body, "the hour wheels rely on scroll snapping"
    assert "sendData" in body


@pytest.mark.asyncio
async def test_the_page_is_not_cached(aiohttp_client):
    """Telegram caches Mini Apps hard; a stale page would survive a deploy."""
    client = await aiohttp_client(webserver.build_app())
    response = await client.get("/")
    assert response.headers["Cache-Control"] == "no-cache"


@pytest.mark.asyncio
async def test_health_endpoint(aiohttp_client):
    client = await aiohttp_client(webserver.build_app())
    assert (await client.get("/healthz")).status == 200


def test_the_page_has_no_external_dependencies_beyond_telegram():
    """Anything else fetched from a CDN would break behind a strict network."""
    html = (webserver.WEBAPP_DIR / "index.html").read_text(encoding="utf-8")
    externals = re.findall(r'(?:src|href)="(https?://[^"]+)"', html)
    assert externals == ["https://telegram.org/js/telegram-web-app.js"], externals


# --------------------------------------------------------------- the payload

def test_valid_payload_is_parsed():
    day, start, end = webapp.parse_payload(
        json.dumps({"date": "2026-06-10", "start": "09:00", "end": "17:30"})
    )
    assert day == dt.date(2026, 6, 10)
    assert (start.hour, start.minute) == (9, 0)
    assert (end.hour, end.minute) == (17, 30)


@pytest.mark.parametrize("payload", [
    "not json",
    "[]",                                                   # not an object
    json.dumps({"start": "09:00", "end": "17:00"}),         # no date
    json.dumps({"date": "2026-06-10", "start": "09:00"}),   # no end
    json.dumps({"date": "10/06/2026", "start": "09:00", "end": "17:00"}),
    json.dumps({"date": "2026-06-10", "start": "9:00", "end": "17:00"}),   # unpadded
    json.dumps({"date": "2026-06-10", "start": "24:00", "end": "17:00"}),
    json.dumps({"date": "2026-06-10", "start": "09:60", "end": "17:00"}),
    json.dumps({"date": "2026-06-10", "start": "09:00", "end": "17:00; DROP TABLE"}),
])
def test_malformed_payloads_are_rejected(payload):
    with pytest.raises(ValueError):
        webapp.parse_payload(payload)


def test_implausible_dates_are_rejected():
    """A date decades out is a broken or tampered payload, not an entry."""
    for bad in ["1990-01-01", "2400-01-01"]:
        with pytest.raises(ValueError):
            webapp.parse_payload(
                json.dumps({"date": bad, "start": "09:00", "end": "17:00"})
            )


# ------------------------------------------------------------------ the flow

@pytest.mark.asyncio
async def test_opening_offers_a_web_app_button_when_configured(webapp_env, ctx):
    update = FakeUpdate(text="/calendar")
    assert await webapp.open_app(update, ctx) is True

    sent = ctx.bot.sent[-1]
    button = sent["reply_markup"].keyboard[0][0]
    assert button.web_app is not None, "sendData needs a reply-keyboard web_app button"
    assert button.web_app.url.startswith(WEBAPP_URL)


@pytest.mark.asyncio
async def test_the_url_carries_the_coming_chag_days(webapp_env, ctx):
    """So the app can mark them before a date is picked."""
    update = FakeUpdate(text="/calendar")
    await webapp.open_app(update, ctx)
    url = ctx.bot.sent[-1]["reply_markup"].keyboard[0][0].web_app.url
    assert "rest=" in url
    assert re.search(r"rest=\d{4}-\d{2}-\d{2}", url)


@pytest.mark.asyncio
async def test_submitting_records_the_shift(webapp_env, ctx):
    update = FakeUpdate(web_app_data=json.dumps(
        {"date": "2026-06-10", "start": "09:00", "end": "15:00"}
    ))
    await webapp.handle_data(update, ctx)

    assert "סה״כ המשמרת" in last_output(update)
    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        shifts = repo.shifts_on_date(s, user.id, dt.date(2026, 6, 10))
        assert len(shifts) == 1
        assert shifts[0].total_agorot == 6 * RATE


@pytest.mark.asyncio
async def test_an_end_before_the_start_means_overnight(webapp_env, ctx):
    update = FakeUpdate(web_app_data=json.dumps(
        {"date": "2026-06-10", "start": "22:00", "end": "04:00"}
    ))
    await webapp.handle_data(update, ctx)

    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        shift = repo.shifts_on_date(s, user.id, dt.date(2026, 6, 10))[0]
        assert sum(seg.hours for seg in shift.segments) == 6.0


@pytest.mark.asyncio
async def test_a_garbage_payload_records_nothing(webapp_env, ctx):
    update = FakeUpdate(web_app_data='{"date": "oops"}')
    await webapp.handle_data(update, ctx)

    assert "לא הצלחתי" in last_output(update)
    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        assert repo.recent_shifts(s, user.id) == []


@pytest.mark.asyncio
async def test_overlapping_hours_are_refused(webapp_env, ctx):
    payload = json.dumps({"date": "2026-06-10", "start": "09:00", "end": "15:00"})
    await webapp.handle_data(FakeUpdate(web_app_data=payload), ctx)

    clash = FakeUpdate(web_app_data=json.dumps(
        {"date": "2026-06-10", "start": "14:00", "end": "18:00"}
    ))
    await webapp.handle_data(clash, ctx)
    assert "חופפת" in last_output(clash)

    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        assert len(repo.shifts_on_date(s, user.id, dt.date(2026, 6, 10))) == 1


@pytest.mark.asyncio
async def test_a_stranger_cannot_submit(webapp_env, ctx):
    update = FakeUpdate(
        web_app_data=json.dumps({"date": "2026-06-10", "start": "09:00", "end": "15:00"}),
        user_id=999,
    )
    await webapp.handle_data(update, ctx)

    with db.session_scope() as s:
        assert repo.recent_shifts(s, 1) == []


# --------------------------------------------------------------- the fallback

@pytest.mark.asyncio
async def test_without_a_url_the_inline_calendar_is_used(bot_env, ctx):
    """No HTTPS address means no Mini App, and the grid must still work."""
    update = FakeUpdate(callback="cal:today")
    assert await webapp.open_app(update, ctx) is False

    await cal_handlers.cb_month(update, ctx)
    _, markup = update.callback_query.edits[-1]
    assert any(d.startswith("cal:d:") for d in callback_data(markup))


@pytest.mark.asyncio
async def test_a_plain_http_url_is_treated_as_disabled(bot_env, ctx):
    """Telegram refuses to open anything but HTTPS, so it must not be offered."""
    common.set_config(_config(bot_env, "http://bot.example.com"))
    assert await webapp.open_app(FakeUpdate(text="/calendar"), ctx) is False


# ------------------------------------------------------- path-prefixed hosting

@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/", "/salary", "/salary/", "/anything/deep"])
async def test_the_page_is_served_under_any_path(aiohttp_client, path):
    """Hosting at a subpath forwards either "/" or "/salary/" depending on
    whether the proxy strips the prefix, and the server cannot tell which."""
    client = await aiohttp_client(webserver.build_app())
    response = await client.get(path)
    assert response.status == 200
    assert "telegram-web-app.js" in await response.text()


@pytest.mark.asyncio
async def test_healthz_is_not_swallowed_by_the_catch_all(aiohttp_client):
    client = await aiohttp_client(webserver.build_app())
    response = await client.get("/healthz")
    assert await response.text() == "ok"


def test_a_prefixed_url_keeps_its_path(tmp_path):
    """WEBAPP_URL=https://host/salary must produce https://host/salary/?rest=..."""
    from salary_bot.config import Config

    config = Config(
        bot_token="1:x", allowed_user_ids=frozenset({TG_ID}),
        db_path=tmp_path / "b.db", log_level="INFO",
        webapp_url="https://srv1515969.hstgr.cloud/salary",
    )
    common.set_config(config)
    url = webapp.webapp_url(FakeContext(), "tel_aviv")
    assert url.startswith("https://srv1515969.hstgr.cloud/salary/?rest=")


def test_a_trailing_slash_is_not_doubled(tmp_path, monkeypatch):
    from salary_bot.config import load_config

    monkeypatch.setenv("BOT_TOKEN", "1:x")
    monkeypatch.setenv("ALLOWED_USER_IDS", "1")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "b.db"))
    monkeypatch.setenv("WEBAPP_URL", "https://srv1515969.hstgr.cloud/salary/")
    assert load_config().webapp_url == "https://srv1515969.hstgr.cloud/salary"
