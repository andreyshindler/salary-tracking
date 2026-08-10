"""Routes free-text messages to whichever prompt is currently awaiting one.

A lightweight alternative to nesting several ConversationHandlers: each prompt
sets ``user_data['awaiting']``, and this dispatches on it. With a handful of
prompts that is far less machinery for the same behaviour.
"""
from __future__ import annotations

import datetime as dt

from telegram import Update
from telegram.ext import ContextTypes

from ...core import timeutil as tu
from ...core.parsing import ParseError, parse_time_of_day
from .. import keyboards as kb
from . import manual, settings, shift
from .common import clear_awaiting, guard


async def _handle_start_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Backdated shift start — "I actually started at 08:30"."""
    today = tu.now_local().date()
    try:
        start_local = parse_time_of_day(update.message.text, today)
    except ParseError as exc:
        await update.message.reply_text(str(exc), reply_markup=kb.cancel_only())
        return

    start_utc = tu.local_naive_to_utc(start_local)
    if start_utc > tu.now_utc():
        # A time later than now must mean yesterday evening, not the future.
        start_local -= dt.timedelta(days=1)
        start_utc = tu.local_naive_to_utc(start_local)

    clear_awaiting(context)
    await shift.start_shift_at(update, context, start_utc)


HANDLERS = {
    "manual": manual.handle_text,
    "rate": settings.handle_rate,
    "ceiling": settings.handle_ceiling,
    "ot_threshold": settings.handle_ot_threshold,
    "start_time": _handle_start_time,
}


async def route(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return

    awaiting = context.user_data.get("awaiting")
    handler = HANDLERS.get(awaiting) if awaiting else None

    if handler is None:
        # Nothing pending: a stray "16:00 21:30" is almost always an attempt to
        # log a shift, so parse it as one. An unparseable message falls through
        # to the manual-entry error, which explains the accepted formats.
        context.user_data["awaiting"] = "manual"
        await manual.handle_text(update, context)
        return

    await handler(update, context)
