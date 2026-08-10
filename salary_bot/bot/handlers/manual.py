"""Manual entry of a shift that was not clocked live."""
from __future__ import annotations

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
from .. import texts_he as T
from .common import clear_awaiting, get_calendar, guard, safe_edit, set_awaiting
from .shift import MAX_SHIFT_HOURS, _ceiling_alert


async def cb_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    set_awaiting(context, "manual")
    await update.callback_query.answer()
    await safe_edit(update.callback_query, T.ASK_MANUAL, kb.cancel_only())


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    set_awaiting(context, "manual")
    await update.message.reply_text(
        T.ASK_MANUAL, reply_markup=kb.cancel_only(), parse_mode=ParseMode.HTML
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Parse a typed shift line and record it."""
    text = update.message.text
    today = tu.now_local().date()

    try:
        start_local, end_local = parse_manual_entry(text, today)
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
        # The ceiling block must describe the month the shift belongs to, not
        # today's. Back-logging a shift from a previous month and being shown
        # the current month's progress would be actively misleading.
        work_date = tu.local_date_of(start_utc)
        status = ceiling_mod.month_status(s, user, work_date.year, work_date.month)
        card = fmt.shift_card(shift, calendar, status)
        shift_id = shift.id
        alert = _ceiling_alert(s, user, status)

    clear_awaiting(context)
    await update.message.reply_text(
        card, reply_markup=kb.after_shift(shift_id), parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    if alert:
        await update.message.reply_text(alert, parse_mode=ParseMode.HTML)
