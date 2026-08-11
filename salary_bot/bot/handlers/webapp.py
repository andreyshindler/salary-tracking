"""Opening the Mini App and recording what it sends back.

``sendData`` only works for a ``web_app`` button on a **reply** keyboard —
Telegram does not deliver it from inline buttons — so opening the app means
sending a one-shot reply keyboard, which is removed again once the data
arrives.

The payload is JSON produced by a page running on the user's phone, so it is
validated here rather than trusted: fields, formats and ranges are all checked
before anything reaches the pricing engine.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re

from telegram import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram import WebAppInfo
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...core import ceiling as ceiling_mod
from ...core import db, repo
from ...core import timeutil as tu
from .. import formatting as fmt
from .. import keyboards as kb
from .. import texts_he as T
from . import common
from .common import get_calendar, guard
from .shift import MAX_SHIFT_HOURS, _ceiling_alert

log = logging.getLogger(__name__)

TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

# Rest days handed to the app so שבת and חג are visible before a date is picked.
REST_LOOKAHEAD_DAYS = 120


def webapp_url(context: ContextTypes.DEFAULT_TYPE, city: str) -> str | None:
    """The app's URL with the coming rest days appended, or None if disabled."""
    config = common.CONFIG
    if config is None or not config.webapp_enabled:
        return None

    calendar = get_calendar(city)
    today = tu.now_local().date()
    rest = [
        (today + dt.timedelta(days=offset)).isoformat()
        for offset in range(-31, REST_LOOKAHEAD_DAYS)
        if calendar.rest_kind(today + dt.timedelta(days=offset)) == "chag"
    ]
    return f"{config.webapp_url}/?rest={','.join(rest)}"


async def open_app(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Offer the Mini App. Returns False when it is not configured, so the
    caller can fall back to the inline calendar."""
    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        url = webapp_url(context, user.city)

    if url is None:
        return False

    markup = ReplyKeyboardMarkup(
        [[KeyboardButton(T.BTN_OPEN_WEBAPP, web_app=WebAppInfo(url=url))]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await context.bot.send_message(
        update.effective_chat.id, T.WEBAPP_PROMPT,
        reply_markup=markup, parse_mode=ParseMode.HTML,
    )
    return True


def parse_payload(raw: str) -> tuple[dt.date, dt.time, dt.time]:
    """Validate the JSON the page sent. Raises ValueError with a Hebrew message."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        raise ValueError(T.WEBAPP_BAD_PAYLOAD)
    if not isinstance(data, dict):
        raise ValueError(T.WEBAPP_BAD_PAYLOAD)

    try:
        day = dt.date.fromisoformat(str(data["date"]))
    except (KeyError, ValueError):
        raise ValueError(T.WEBAPP_BAD_PAYLOAD)

    times = []
    for field in ("start", "end"):
        match = TIME_RE.match(str(data.get(field, "")))
        if match is None:
            raise ValueError(T.WEBAPP_BAD_PAYLOAD)
        times.append(dt.time(int(match.group(1)), int(match.group(2))))

    # A date far outside any plausible working life is a sign of a broken or
    # tampered payload rather than a real entry.
    today = tu.now_local().date()
    if not (today - dt.timedelta(days=3650) <= day <= today + dt.timedelta(days=370)):
        raise ValueError(T.WEBAPP_BAD_DATE)

    return day, times[0], times[1]


async def handle_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return

    try:
        day, start_time, end_time = parse_payload(update.message.web_app_data.data)
    except ValueError as exc:
        log.warning("Rejected a Mini App payload: %s", exc)
        await update.message.reply_text(str(exc), reply_markup=ReplyKeyboardRemove())
        return

    start_local = dt.datetime.combine(day, start_time)
    end_local = dt.datetime.combine(day, end_time)
    if end_local <= start_local:
        end_local += dt.timedelta(days=1)   # crossed midnight

    start_utc = tu.local_naive_to_utc(start_local)
    end_utc = tu.local_naive_to_utc(end_local)
    if (end_utc - start_utc) > dt.timedelta(hours=MAX_SHIFT_HOURS):
        await update.message.reply_text(T.SHIFT_TOO_LONG, reply_markup=ReplyKeyboardRemove())
        return

    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)

        clash = repo.overlapping_shift(s, user.id, start_utc, end_utc)
        if clash is not None:
            msg = T.SHIFT_OVERLAP.format(
                start=tu.to_local(clash.start_utc).strftime("%d.%m %H:%M"),
                end=tu.to_local(clash.end_utc).strftime("%H:%M"),
            )
            await update.message.reply_text(msg, reply_markup=ReplyKeyboardRemove())
            return

        calendar = get_calendar(user.city)
        shift = repo.add_manual_shift(s, user, start_utc, end_utc, calendar)
        status = ceiling_mod.month_status(s, user, day.year, day.month)
        card = fmt.shift_card(shift, calendar, status)
        shift_id = shift.id
        alert = _ceiling_alert(s, user, status)

    # Drop the one-shot keyboard, then show the result with the usual actions.
    await update.message.reply_text("✅", reply_markup=ReplyKeyboardRemove())
    await update.message.reply_text(
        card, reply_markup=kb.after_shift(shift_id), parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    if alert:
        await update.message.reply_text(alert, parse_mode=ParseMode.HTML)
