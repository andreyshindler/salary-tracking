"""The calendar: pick a date from a month grid, then enter the hours.

Complements manual entry rather than replacing it. Typing "אתמול 16:00 21:30"
stays the fastest path for recent days; the grid is for filling in a date
further back, and for seeing at a glance which days already have hours on them
and which are חג before you work them.
"""
from __future__ import annotations

import calendar as pycalendar
import datetime as dt

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...core import ceiling as ceiling_mod
from ...core import db, repo
from ...core import timeutil as tu
from ...core.parsing import ParseError, parse_manual_entry
from .. import formatting as fmt
from .. import keyboards as kb
from .. import month_grid as grid
from .. import texts_he as T
from . import webapp
from .common import clear_awaiting, get_calendar, guard, safe_edit, set_awaiting
from .shift import MAX_SHIFT_HOURS, _ceiling_alert


async def _reply(update: Update, text: str, markup=None) -> None:
    if update.callback_query:
        await update.callback_query.answer()
        await safe_edit(update.callback_query, text, markup)
    else:
        await update.message.reply_text(
            text, reply_markup=markup, parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


def _render_month(s, user, year: int, month: int):
    calendar = get_calendar(user.city)
    logged = repo.days_with_shifts(s, user.id, year, month)

    last_day = pycalendar.monthrange(year, month)[1]
    chag_days = {
        day for day in range(1, last_day + 1)
        if calendar.rest_kind(dt.date(year, month, day)) == "chag"
    }

    status = ceiling_mod.month_status(s, user, year, month)
    text = "\n".join([
        fmt.rtl(T.CALENDAR_TITLE.format(month=fmt.fmt_month(year, month))),
        "",
        fmt.ceiling_block(status, with_month=False),
        "",
        fmt.rtl(T.CALENDAR_HINT),
        fmt.rtl(T.CALENDAR_LEGEND),
    ])
    markup = grid.month_grid(year, month, logged, chag_days, today=tu.now_local().date())
    return text, markup


async def cb_month(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    clear_awaiting(context)

    data = update.callback_query.data
    if data == "cal:today":
        if await webapp.open_app(update, context):
            await update.callback_query.answer()
            return
        today = tu.now_local().date()
        year, month = today.year, today.month
    else:
        _, _, year_s, month_s = data.split(":")
        year, month = int(year_s), int(month_s)

    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        text, markup = _render_month(s, user, year, month)
    await _reply(update, text, markup)


async def cmd_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    clear_awaiting(context)
    # The Mini App is the nicer picker, but it needs a public HTTPS address.
    # Without one, the inline grid does the same job with no infrastructure.
    if await webapp.open_app(update, context):
        return
    today = tu.now_local().date()
    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        text, markup = _render_month(s, user, today.year, today.month)
    await _reply(update, text, markup)


def _parse_day(data: str) -> dt.date:
    _, _, year, month, day = data.split(":")
    return dt.date(int(year), int(month), int(day))


async def cb_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    clear_awaiting(context)
    day = _parse_day(update.callback_query.data)

    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        calendar = get_calendar(user.city)
        shifts = repo.shifts_on_date(s, user.id, day)

        header = fmt.rtl(f"🗓 <b>{fmt.fmt_date(day)}</b>")
        holiday = calendar.holiday_label(day)
        if holiday:
            header += fmt.rtl(f"\n🕯 {holiday}")

        lines = [header, ""]
        if shifts:
            lines += [fmt.shift_line(sh, calendar) for sh in shifts]
            total = sum(sh.total_agorot for sh in shifts)
            hours = sum(seg.hours for sh in shifts for seg in sh.segments)
            lines += ["", fmt.rtl(
                f"💰 <b>סה״כ ליום: {fmt.fmt_money(total)}</b> · {fmt.fmt_hours(hours)} שעות"
            )]
        else:
            lines.append(fmt.rtl(T.CALENDAR_DAY_EMPTY))

        text = "\n".join(lines)
        markup = grid.day_menu(day, shifts)
    await _reply(update, text, markup)


async def cb_add_hours(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    day = _parse_day(update.callback_query.data)
    set_awaiting(context, "day_hours", day.isoformat())
    await _reply(
        update,
        T.ASK_DAY_HOURS.format(date=fmt.fmt_date(day)),
        kb.cancel_only(),
    )


async def handle_hours(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Hours typed after a date was picked from the grid.

    The chosen date is passed to the manual parser as "today", so a bare
    "16:00 21:30" lands on that day and every other accepted shape — including
    an end before the start meaning an overnight shift — still works.
    """
    raw = context.user_data.get("awaiting_arg")
    if not raw:
        clear_awaiting(context)
        await update.message.reply_text(T.ERROR_GENERIC)
        return
    day = dt.date.fromisoformat(raw)

    try:
        start_local, end_local = parse_manual_entry(update.message.text, day)
    except ParseError as exc:
        await update.message.reply_text(str(exc), reply_markup=kb.cancel_only())
        return

    start_utc = tu.local_naive_to_utc(start_local)
    end_utc = tu.local_naive_to_utc(end_local)
    if (end_utc - start_utc) > dt.timedelta(hours=MAX_SHIFT_HOURS):
        await update.message.reply_text(T.SHIFT_TOO_LONG, reply_markup=kb.cancel_only())
        return

    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)

        clash = repo.overlapping_shift(s, user.id, start_utc, end_utc)
        if clash is not None:
            msg = T.SHIFT_OVERLAP.format(
                start=tu.to_local(clash.start_utc).strftime("%d.%m %H:%M"),
                end=tu.to_local(clash.end_utc).strftime("%H:%M"),
            )
            await update.message.reply_text(msg, reply_markup=kb.cancel_only())
            return

        calendar = get_calendar(user.city)
        shift = repo.add_manual_shift(s, user, start_utc, end_utc, calendar)
        status = ceiling_mod.month_status(s, user, day.year, day.month)
        card = fmt.shift_card(shift, calendar, status)
        alert = _ceiling_alert(s, user, status)
        # Straight back to the grid, so several days can be filled in a row.
        _, markup = _render_month(s, user, day.year, day.month)

    clear_awaiting(context)
    await update.message.reply_text(
        card, reply_markup=markup, parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    if alert:
        await update.message.reply_text(alert, parse_mode=ParseMode.HTML)


async def cb_noop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Padding cells and the weekday header still need a callback."""
    await update.callback_query.answer()
