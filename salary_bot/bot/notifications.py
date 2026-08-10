"""Scheduled reminders, run on the bot's JobQueue.

Three jobs, each independently switchable from Settings:

* an open shift left running (someone forgot to press stop);
* a monthly summary when the ceiling counter resets;
* ceiling-threshold alerts, which are emitted inline when a shift is logged
  rather than on a timer — the useful moment is right after the hours land.
"""
from __future__ import annotations

import datetime as dt
import logging

from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ..config import ISRAEL_TZ
from ..core import access
from ..core import ceiling as ceiling_mod
from ..core import db, repo
from ..core import timeutil as tu
from . import formatting as fmt
from . import texts_he as T

log = logging.getLogger(__name__)

OPEN_SHIFT_ALERT_AFTER_HOURS = 12


async def check_open_shifts(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Nudge about a shift that has been running unusually long.

    The set of already-warned shifts lives in ``bot_data`` rather than the
    database: a restart re-sending one reminder is harmless, and it keeps a
    purely transient concern out of the schema.
    """
    warned: set[int] = context.bot_data.setdefault("warned_open_shifts", set())
    now = tu.now_utc()

    with db.session_scope() as s:
        users = access.approved_users(s)
        pending: list[tuple[int, str, float]] = []
        for user in users:
            if not user.notify_open_shift:
                continue
            shift = repo.open_shift(s, user.id)
            if shift is None or shift.id in warned:
                continue
            hours = (now - shift.start_utc).total_seconds() / 3600
            if hours >= OPEN_SHIFT_ALERT_AFTER_HOURS:
                warned.add(shift.id)
                pending.append((
                    user.tg_user_id,
                    tu.to_local(shift.start_utc).strftime("%d.%m %H:%M"),
                    hours,
                ))

    for tg_id, start_label, hours in pending:
        try:
            await context.bot.send_message(
                tg_id,
                T.ALERT_OPEN_SHIFT.format(start=start_label, hours=fmt.fmt_hours(hours)),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            log.exception("Could not send open-shift reminder to %s", tg_id)


async def month_rollover(context: ContextTypes.DEFAULT_TYPE) -> None:
    """On the 1st, summarise the month that just ended."""
    today = tu.now_local().date()
    if today.day != 1:
        return

    previous = today - dt.timedelta(days=1)
    with db.session_scope() as s:
        users = access.approved_users(s)
        messages: list[tuple[int, str]] = []
        for user in users:
            if not user.notify_month_summary:
                continue
            status = ceiling_mod.month_status(s, user, previous.year, previous.month)
            if status.shift_count == 0:
                continue
            messages.append((
                user.tg_user_id,
                T.MONTH_RESET.format(
                    month=fmt.fmt_month(previous.year, previous.month),
                    earned=fmt.fmt_money(status.earned_agorot),
                    ceiling=fmt.fmt_money(status.ceiling_agorot),
                    hours=fmt.fmt_hours(status.total_hours),
                    count=status.shift_count,
                ),
            ))

    for tg_id, text in messages:
        try:
            await context.bot.send_message(tg_id, text, parse_mode=ParseMode.HTML)
        except Exception:
            log.exception("Could not send the monthly summary to %s", tg_id)


def register(job_queue) -> None:
    job_queue.run_repeating(
        check_open_shifts,
        interval=dt.timedelta(hours=1),
        first=dt.timedelta(minutes=2),
        name="open-shift-check",
    )
    job_queue.run_daily(
        month_rollover,
        time=dt.time(hour=8, minute=0, tzinfo=ISRAEL_TZ),
        name="month-rollover",
    )
