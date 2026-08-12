"""Opening the Mini App and recording what it sends back.

The app is launched straight from the diary button in the main menu, so there
is no intermediate message to press through. That button is an *inline*
``web_app`` button, and Telegram does not deliver ``sendData`` from those — the
page posts its result back to the bot's own web server instead, signed by
Telegram so we know who sent it. :mod:`salary_bot.core.webauth` does the
checking.

``sendData`` is still handled: a one-time reply keyboard from an earlier
version can survive on a phone long after the bot stopped offering one, and
pressing it should record the shift rather than do nothing.

Either way the payload is JSON built by a page running on the user's phone, so
it is validated here rather than trusted: fields, formats and ranges are all
checked before anything reaches the pricing engine.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re

from telegram import ReplyKeyboardRemove, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...core import access, ceiling as ceiling_mod
from ...core import db, repo, webauth
from ...core import timeutil as tu
from .. import formatting as fmt
from .. import keyboards as kb
from .. import report_payload
from .. import texts_he as T
from . import common, reports
from .common import calendar_url, get_calendar, guard
from .shift import MAX_SHIFT_HOURS, _ceiling_alert

log = logging.getLogger(__name__)

TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class Rejected(ValueError):
    """A refusal with a Hebrew reason fit to show the user."""


async def open_app(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Offer the Mini App from a command, where there is no menu button to hang
    it on. Returns False when it is not configured, so the caller can fall back
    to the inline calendar."""
    url = calendar_url()
    if url is None:
        return False

    await context.bot.send_message(
        update.effective_chat.id, T.WEBAPP_PROMPT,
        reply_markup=kb.open_webapp(url), parse_mode=ParseMode.HTML,
    )
    return True


def parse_payload(raw: str) -> tuple[dt.date, dt.time, dt.time]:
    """Validate the JSON the page sent. Raises Rejected with a Hebrew message."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        raise Rejected(T.WEBAPP_BAD_PAYLOAD)
    if not isinstance(data, dict):
        raise Rejected(T.WEBAPP_BAD_PAYLOAD)

    try:
        day = dt.date.fromisoformat(str(data["date"]))
    except (KeyError, ValueError):
        raise Rejected(T.WEBAPP_BAD_PAYLOAD)

    times = []
    for field in ("start", "end"):
        match = TIME_RE.match(str(data.get(field, "")))
        if match is None:
            raise Rejected(T.WEBAPP_BAD_PAYLOAD)
        times.append(dt.time(int(match.group(1)), int(match.group(2))))

    # A date far outside any plausible working life is a sign of a broken or
    # tampered payload rather than a real entry.
    today = tu.now_local().date()
    if not (today - dt.timedelta(days=3650) <= day <= today + dt.timedelta(days=370)):
        raise Rejected(T.WEBAPP_BAD_DATE)

    return day, times[0], times[1]


async def record(bot, tg_user_id: int, raw_payload: str) -> None:
    """Store the shift and send the breakdown. Raises Rejected if it cannot.

    Messages go out through the bot rather than as a reply, because the POST
    path has no message to reply to.
    """
    day, start_time, end_time = parse_payload(raw_payload)

    start_local = dt.datetime.combine(day, start_time)
    end_local = dt.datetime.combine(day, end_time)
    if end_local <= start_local:
        end_local += dt.timedelta(days=1)   # crossed midnight

    start_utc = tu.local_naive_to_utc(start_local)
    end_utc = tu.local_naive_to_utc(end_local)
    if (end_utc - start_utc) > dt.timedelta(hours=MAX_SHIFT_HOURS):
        raise Rejected(T.SHIFT_TOO_LONG)

    with db.session_scope() as s:
        user = db.get_or_create_user(s, tg_user_id)

        clash = repo.overlapping_shift(s, user.id, start_utc, end_utc)
        if clash is not None:
            raise Rejected(T.SHIFT_OVERLAP.format(
                start=tu.to_local(clash.start_utc).strftime("%d.%m %H:%M"),
                end=tu.to_local(clash.end_utc).strftime("%H:%M"),
            ))

        calendar = get_calendar(user.city)
        shift = repo.add_manual_shift(s, user, start_utc, end_utc, calendar)
        status = ceiling_mod.month_status(s, user, day.year, day.month)
        card = fmt.shift_card(shift, calendar, status)
        shift_id = shift.id
        alert = _ceiling_alert(s, user, status)

    await bot.send_message(
        tg_user_id, card, reply_markup=kb.after_shift(shift_id),
        parse_mode=ParseMode.HTML, disable_web_page_preview=True,
    )
    if alert:
        await bot.send_message(tg_user_id, alert, parse_mode=ParseMode.HTML)


# ------------------------------------------------------------- the POST API

def _is_approved(tg_user_id: int) -> bool:
    """The same gate the message handlers apply, without an Update to hand.

    A signed launch proves *which* Telegram account is posting, not that the
    account is allowed to; access is still decided here.
    """
    bootstrap = common.CONFIG.allowed_user_ids if common.CONFIG else frozenset()
    with db.session_scope() as s:
        user = db.get_or_create_user(s, tg_user_id)
        access.apply_bootstrap(s, user, bootstrap)
        return access.is_approved(user)


def build_api(bot, bot_token: str) -> dict:
    """The endpoints the page may call, each behind the signature check.

    Authentication lives here rather than in the web server so that adding an
    endpoint cannot accidentally add an unauthenticated one.
    """

    def authenticated(handler):
        async def wrapped(init_data: str, body: dict) -> tuple[int, dict]:
            try:
                tg_user_id = webauth.verify_init_data(init_data, bot_token)
            except webauth.InitDataError as exc:
                log.warning("Refused an unverified Mini App request: %s", exc)
                return 401, {"message": T.WEBAPP_UNVERIFIED}

            if not _is_approved(tg_user_id):
                log.warning("Refused a Mini App request from %s: no access", tg_user_id)
                return 403, {"message": T.WEBAPP_NO_ACCESS}

            try:
                return await handler(tg_user_id, body)
            except Rejected as exc:
                log.info("Rejected a Mini App request from %s: %s", tg_user_id, exc)
                return 400, {"message": str(exc)}

        return wrapped

    async def shift(tg_user_id: int, body: dict) -> tuple[int, dict]:
        payload = body.get("shift")
        if not isinstance(payload, str):
            raise Rejected(T.WEBAPP_BAD_PAYLOAD)
        await record(bot, tg_user_id, payload)
        return 200, {"message": "ok"}

    async def report(tg_user_id: int, body: dict) -> tuple[int, dict]:
        year, month = report_payload.parse_month(body)
        with db.session_scope() as s:
            user = db.get_or_create_user(s, tg_user_id)
            calendar = get_calendar(user.city)
            return 200, report_payload.build(s, user, calendar, year, month)

    async def export(tg_user_id: int, body: dict) -> tuple[int, dict]:
        year, _ = report_payload.parse_month(body)
        await reports.send_csv(bot, tg_user_id, year or tu.now_local().year)
        return 200, {"message": T.WEBAPP_EXPORT_SENT}

    return {
        "shift": authenticated(shift),
        "report": authenticated(report),
        "export": authenticated(export),
    }


# ------------------------------------------- sendData, from an older keyboard

async def handle_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return

    # Whatever reply keyboard produced this is stale; take it off the screen.
    await update.message.reply_text("✅", reply_markup=ReplyKeyboardRemove())
    try:
        await record(context.bot, update.effective_user.id,
                     update.message.web_app_data.data)
    except Rejected as exc:
        await update.message.reply_text(str(exc))
