"""The Mini App: the served page, the submission it posts back, and the fallback.

The payload is JSON built by a page running on the user's phone, so it is
treated as untrusted input and validated rather than believed — and since it
arrives over a public HTTP endpoint rather than through Telegram, so is the
identity attached to it.
"""
from __future__ import annotations

import datetime as dt
import json
import re

import pytest

from salary_bot.bot import formatting as fmt
from salary_bot.bot import keyboards as kb
from salary_bot.bot import webserver
from salary_bot.bot.handlers import calendar as cal_handlers
from salary_bot.bot.handlers import common
from salary_bot.bot.handlers import webapp
from salary_bot.core import db, repo
from tests.conftest import NIGHT_RATE, RATE
from tests.stubs import TG_ID, FakeBot, FakeContext, FakeUpdate, callback_data
from tests.stubs import last_output
from tests.test_webauth import launch

WEBAPP_URL = "https://bot.example.com"
TOKEN = "123:FAKE"


def _config(tmp_path, url: str = ""):
    from salary_bot.config import Config

    return Config(
        bot_token=TOKEN,
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


def bot_texts(bot: FakeBot) -> list[str]:
    return [text for _, text in bot.messages]


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
    assert 'base + "api/"' in body, "the page must post its result back to the bot"


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


def test_the_page_posts_inside_its_own_directory():
    """Hosting at /salary must not produce a request to /api/shift, which the
    reverse proxy would never route to this server."""
    html = (webserver.WEBAPP_DIR / "index.html").read_text(encoding="utf-8")
    assert 'location.pathname.endsWith("/")' in html
    assert '"/api/"' not in html, "an absolute path would escape the prefix"


# ------------------------------------------------------- opening it, one tap

def test_the_menu_diary_button_opens_the_app_directly(webapp_env):
    """One press, no intermediate message with a second button."""
    markup = common.main_menu_markup(TG_ID)
    diary = [b for row in markup.inline_keyboard for b in row if "יומן" in b.text][0]
    assert diary.web_app is not None, "the diary must launch the app itself"
    assert diary.web_app.url.startswith(WEBAPP_URL)
    assert diary.callback_data is None


def test_without_the_app_the_diary_button_opens_the_grid(bot_env):
    markup = common.main_menu_markup(TG_ID)
    diary = [b for row in markup.inline_keyboard for b in row if "יומן" in b.text][0]
    assert diary.web_app is None
    assert diary.callback_data == "cal:today"


def test_the_url_carries_the_coming_chag_days(webapp_env):
    """So the app can mark them before a date is picked."""
    url = common.calendar_url()
    assert re.search(r"rest=\d{4}-\d{2}-\d{2}", url)


@pytest.mark.asyncio
async def test_the_command_offers_a_web_app_button(webapp_env, ctx):
    """/calendar has no menu button to hang the app on, so it sends one."""
    assert await webapp.open_app(FakeUpdate(text="/calendar"), ctx) is True

    button = ctx.bot.sent[-1]["reply_markup"].inline_keyboard[0][0]
    assert button.web_app is not None
    assert button.web_app.url.startswith(WEBAPP_URL)


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
    with pytest.raises(webapp.Rejected):
        webapp.parse_payload(payload)


def test_implausible_dates_are_rejected():
    """A date decades out is a broken or tampered payload, not an entry."""
    for bad in ["1990-01-01", "2400-01-01"]:
        with pytest.raises(webapp.Rejected):
            webapp.parse_payload(
                json.dumps({"date": bad, "start": "09:00", "end": "17:00"})
            )


# ------------------------------------------------------- submitting over HTTP

@pytest.fixture()
def posting(webapp_env):
    """A client posting to the real endpoint, and the bot it answers through."""
    bot = FakeBot()

    async def make(aiohttp_client):
        app = webserver.build_app(webapp.build_api(bot, TOKEN))
        return await aiohttp_client(app)

    return bot, make


def signed(user_id: int = TG_ID, token: str = TOKEN) -> str:
    """A launch string signed with this bot's token, dated now."""
    return launch(user_id=user_id, at=dt.datetime.now(dt.timezone.utc), token=token)


async def post_shift(client, init_data: str, shift: dict, path="/api/shift"):
    return await client.post(path, json={"initData": init_data, "shift": json.dumps(shift)})


@pytest.mark.asyncio
async def test_a_signed_submission_records_the_shift(aiohttp_client, posting):
    bot, make = posting
    client = await make(aiohttp_client)

    response = await post_shift(
        client, signed(),
        {"date": "2026-06-10", "start": "09:00", "end": "15:00"},
    )
    assert response.status == 200

    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        shifts = repo.shifts_on_date(s, user.id, dt.date(2026, 6, 10))
        assert len(shifts) == 1
        assert shifts[0].total_agorot == 6 * RATE

    assert any("סה״כ המשמרת" in text for text in bot_texts(bot)), \
        "the breakdown must reach the user, since the page only closes itself"


@pytest.mark.asyncio
async def test_an_unsigned_submission_records_nothing(aiohttp_client, posting):
    """Anyone can reach this URL; only Telegram can sign for a user."""
    bot, make = posting
    client = await make(aiohttp_client)

    response = await post_shift(
        client, "user=%7B%22id%22%3A111%7D&auth_date=1&hash=deadbeef",
        {"date": "2026-06-10", "start": "09:00", "end": "15:00"},
    )
    assert response.status == 401

    with db.session_scope() as s:
        assert repo.recent_shifts(s, 1) == []
    assert bot.messages == []


@pytest.mark.asyncio
async def test_a_submission_signed_with_another_token_records_nothing(
    aiohttp_client, posting
):
    """Guards against the endpoint accepting any well-formed initData."""
    bot, make = posting
    client = await make(aiohttp_client)

    forged = signed(token="999:not-the-bot-token")
    response = await post_shift(
        client, forged, {"date": "2026-06-10", "start": "09:00", "end": "15:00"},
    )
    assert response.status == 401

    with db.session_scope() as s:
        assert repo.recent_shifts(s, 1) == []


@pytest.mark.asyncio
async def test_a_stranger_with_a_real_signature_is_still_refused(
    aiohttp_client, posting
):
    """A signed launch proves who you are, not that you are allowed in."""
    bot, make = posting
    client = await make(aiohttp_client)

    response = await post_shift(
        client, signed(999),
        {"date": "2026-06-10", "start": "09:00", "end": "15:00"},
    )
    assert response.status == 403

    with db.session_scope() as s:
        stranger = db.get_or_create_user(s, 999)
        assert repo.recent_shifts(s, stranger.id) == []


@pytest.mark.asyncio
async def test_a_garbage_payload_from_a_real_user_records_nothing(
    aiohttp_client, posting
):
    bot, make = posting
    client = await make(aiohttp_client)

    response = await post_shift(
        client, signed(),
        {"date": "oops"},
    )
    assert response.status == 400
    assert "לא הצלחתי" in (await response.json())["message"]

    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        assert repo.recent_shifts(s, user.id) == []


@pytest.mark.asyncio
async def test_overlapping_hours_are_refused(aiohttp_client, posting):
    bot, make = posting
    client = await make(aiohttp_client)
    launch_data = signed()

    first = await post_shift(
        client, launch_data, {"date": "2026-06-10", "start": "09:00", "end": "15:00"})
    assert first.status == 200

    clash = await post_shift(
        client, launch_data, {"date": "2026-06-10", "start": "14:00", "end": "18:00"})
    assert clash.status == 400
    assert "חופפת" in (await clash.json())["message"]

    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        assert len(repo.shifts_on_date(s, user.id, dt.date(2026, 6, 10))) == 1


@pytest.mark.asyncio
async def test_an_end_before_the_start_means_overnight(aiohttp_client, posting):
    bot, make = posting
    client = await make(aiohttp_client)

    await post_shift(
        client, signed(),
        {"date": "2026-06-10", "start": "22:00", "end": "04:00"},
    )
    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        shift = repo.shifts_on_date(s, user.id, dt.date(2026, 6, 10))[0]
        assert sum(seg.hours for seg in shift.segments) == 6.0


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/shift", "/salary/api/shift"])
async def test_the_endpoint_answers_with_or_without_the_path_prefix(
    aiohttp_client, posting, path
):
    """Whether the proxy strips /salary is not something this server can see."""
    bot, make = posting
    client = await make(aiohttp_client)

    response = await post_shift(
        client, signed(),
        {"date": "2026-06-10", "start": "09:00", "end": "15:00"}, path=path,
    )
    assert response.status == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    "not json", "[]", '{"shift": "{}"}', '{"initData": 5, "shift": "{}"}',
])
async def test_a_malformed_request_body_is_rejected(aiohttp_client, posting, body):
    bot, make = posting
    client = await make(aiohttp_client)

    response = await client.post(
        "/api/shift", data=body, headers={"Content-Type": "application/json"})
    assert response.status == 400


@pytest.mark.asyncio
async def test_an_oversized_body_is_dropped(aiohttp_client, posting):
    bot, make = posting
    client = await make(aiohttp_client)

    response = await client.post("/api/shift", data="x" * (webserver.MAX_BODY_BYTES + 1))
    assert response.status in (400, 413)
    assert bot.messages == []


# ------------------------------------------------------------------ reports

def test_the_menu_reports_button_opens_the_app(webapp_env):
    markup = common.main_menu_markup(TG_ID)
    reports = [b for row in markup.inline_keyboard for b in row if "דוחות" in b.text][0]
    assert reports.web_app is not None
    assert reports.web_app.url.endswith("?view=reports"), \
        "the same page, opened on its reports screen"


def test_without_the_app_reports_stay_in_the_chat(bot_env):
    markup = common.main_menu_markup(TG_ID)
    reports = [b for row in markup.inline_keyboard for b in row if "דוחות" in b.text][0]
    assert reports.web_app is None
    assert reports.callback_data == "rep:menu"


@pytest.mark.asyncio
async def test_the_report_reflects_the_logged_hours(aiohttp_client, posting):
    bot, make = posting
    client = await make(aiohttp_client)
    await post_shift(client, signed(),
                     {"date": "2026-06-10", "start": "09:00", "end": "15:00"})

    response = await client.post(
        "/api/report", json={"initData": signed(), "year": 2026, "month": 6})
    assert response.status == 200
    data = await response.json()

    assert data["month"]["label"] == "יוני 2026"
    assert data["month"]["shiftCount"] == 1
    assert data["month"]["hours"] == "6"
    assert data["month"]["earned"] == fmt.fmt_money(6 * RATE)
    assert [t["pct"] for t in data["month"]["tiers"]] == ["100%"]
    assert data["month"]["shifts"][0]["date"] == "10.06"

    assert [r["short"] for r in data["year"]["rows"]] == ["יוני"]
    assert data["year"]["earned"] == fmt.fmt_money(6 * RATE)
    assert {"year": 2026, "month": 6} in [
        {"year": m["year"], "month": m["month"]} for m in data["months"]
    ]


@pytest.mark.asyncio
async def test_a_month_with_nothing_in_it_reports_zero(aiohttp_client, posting):
    """Stepping back through months must not fail on an empty one."""
    bot, make = posting
    client = await make(aiohttp_client)

    response = await client.post(
        "/api/report", json={"initData": signed(), "year": 2019, "month": 3})
    data = await response.json()
    assert response.status == 200
    assert data["month"]["shiftCount"] == 0
    assert data["month"]["tiers"] == []
    assert data["month"]["shifts"] == []


@pytest.mark.asyncio
async def test_a_nonsense_month_falls_back_to_today(aiohttp_client, posting):
    bot, make = posting
    client = await make(aiohttp_client)

    response = await client.post(
        "/api/report", json={"initData": signed(), "year": "; DROP", "month": 99})
    assert response.status == 200
    today = dt.date.today()
    data = await response.json()
    assert (data["month"]["year"], data["month"]["month"]) == (today.year, today.month)


@pytest.mark.asyncio
async def test_a_stranger_cannot_read_the_report(aiohttp_client, posting):
    """The report is somebody's earnings; a signature is not permission."""
    bot, make = posting
    client = await make(aiohttp_client)

    response = await client.post("/api/report", json={"initData": signed(999)})
    assert response.status == 403
    assert "month" not in await response.json()


@pytest.mark.asyncio
async def test_an_unsigned_request_cannot_read_the_report(aiohttp_client, posting):
    bot, make = posting
    client = await make(aiohttp_client)

    response = await client.post(
        "/api/report", json={"initData": signed(token="999:wrong")})
    assert response.status == 401


@pytest.mark.asyncio
async def test_export_sends_the_csv_to_the_chat(aiohttp_client, posting):
    bot, make = posting
    client = await make(aiohttp_client)
    await post_shift(client, signed(),
                     {"date": "2026-06-10", "start": "09:00", "end": "15:00"})

    response = await client.post(
        "/api/export", json={"initData": signed(), "year": 2026, "month": 6})
    assert response.status == 200

    assert len(bot.documents) == 1
    assert bot.documents[0]["chat_id"] == TG_ID


@pytest.mark.asyncio
async def test_a_stranger_cannot_trigger_an_export(aiohttp_client, posting):
    bot, make = posting
    client = await make(aiohttp_client)

    response = await client.post("/api/export", json={"initData": signed(999)})
    assert response.status == 403
    assert bot.documents == []


@pytest.mark.asyncio
async def test_an_unknown_endpoint_is_not_served(aiohttp_client, posting):
    bot, make = posting
    client = await make(aiohttp_client)

    response = await client.post("/api/whatever", json={"initData": signed()})
    assert response.status == 404


# ----------------------------------------- sendData, from a stale keyboard

@pytest.mark.asyncio
async def test_a_leftover_reply_keyboard_still_records(webapp_env, ctx):
    """A one-time keyboard from an older version can outlive it on a phone."""
    update = FakeUpdate(web_app_data=json.dumps(
        {"date": "2026-06-10", "start": "09:00", "end": "15:00"}
    ))
    await webapp.handle_data(update, ctx)

    assert any("סה״כ המשמרת" in text for text in bot_texts(ctx.bot))
    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        assert len(repo.shifts_on_date(s, user.id, dt.date(2026, 6, 10))) == 1


@pytest.mark.asyncio
async def test_sent_data_from_a_stranger_records_nothing(webapp_env, ctx):
    update = FakeUpdate(
        web_app_data=json.dumps({"date": "2026-06-10", "start": "09:00", "end": "15:00"}),
        user_id=999,
    )
    await webapp.handle_data(update, ctx)

    with db.session_scope() as s:
        assert repo.recent_shifts(s, 1) == []


@pytest.mark.asyncio
async def test_sent_garbage_is_reported(webapp_env, ctx):
    update = FakeUpdate(web_app_data='{"date": "oops"}')
    await webapp.handle_data(update, ctx)

    assert "לא הצלחתי" in last_output(update)
    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        assert repo.recent_shifts(s, user.id) == []


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
    assert kb.calendar_button(common.calendar_url()).callback_data == "cal:today"


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
    assert common.calendar_url().startswith("https://srv1515969.hstgr.cloud/salary/?rest=")


def test_a_trailing_slash_is_not_doubled(tmp_path, monkeypatch):
    from salary_bot.config import load_config

    monkeypatch.setenv("BOT_TOKEN", "1:x")
    monkeypatch.setenv("ALLOWED_USER_IDS", "1")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "b.db"))
    monkeypatch.setenv("WEBAPP_URL", "https://srv1515969.hstgr.cloud/salary/")
    assert load_config().webapp_url == "https://srv1515969.hstgr.cloud/salary"
