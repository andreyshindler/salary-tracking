"""Starting, ending, listing and deleting shifts."""
from __future__ import annotations

import datetime as dt

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...core import ceiling as ceiling_mod
from ...core import db, repo
from ...core import timeutil as tu
from ...core.pay_engine import estimate_hours_for_amount
from .. import formatting as fmt
from .. import keyboards as kb
from .. import texts_he as T
from .common import (
    app_links, clear_awaiting, get_calendar, guard, main_menu_markup,
    safe_edit, set_awaiting,
)

MAX_SHIFT_HOURS = 24



async def _reply(update: Update, text: str, markup=None) -> None:
    if update.callback_query:
        await update.callback_query.answer()
        await safe_edit(update.callback_query, text, markup)
    else:
        await update.message.reply_text(
            text, reply_markup=markup, parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


# ------------------------------------------------------------------- starting

async def start_shift_at(update: Update, context: ContextTypes.DEFAULT_TYPE,
                         start_utc: dt.datetime) -> None:
    tg_id = update.effective_user.id
    with db.session_scope() as s:
        user = db.get_or_create_user(s, tg_id)
        existing = repo.open_shift(s, user.id)
        if existing is not None:
            text = T.SHIFT_ALREADY_OPEN.format(
                start=tu.to_local(existing.start_utc).strftime("%d.%m %H:%M")
            )
            await _reply(update, text, kb.main_menu(True, app_links()))
            return

        if start_utc > tu.now_utc():
            await _reply(update, T.SHIFT_START_IN_FUTURE, kb.main_menu(False, app_links()))
            return

        calendar = get_calendar(user.city)
        repo.start_shift(s, user.id, start_utc)

    # Telling the user which rate is running right now is the whole point of
    # showing anything at all at start time.
    is_rest, label = calendar.is_rest_at(tu.to_aware_utc(start_utc))
    tier = f"{label} · 150%" if is_rest else "רגיל · 100%"
    text = T.SHIFT_STARTED.format(
        start=tu.to_local(start_utc).strftime("%H:%M"), tier=tier
    )
    await _reply(update, text, kb.main_menu(True, app_links()))


async def cb_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    clear_awaiting(context)
    await start_shift_at(update, context, tu.now_utc())


async def cb_start_earlier(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    set_awaiting(context, "start_time")
    await _reply(update, T.ASK_START_TIME, kb.cancel_only())


# -------------------------------------------------------------------- ending

async def cb_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    clear_awaiting(context)
    tg_id = update.effective_user.id

    with db.session_scope() as s:
        user = db.get_or_create_user(s, tg_id)
        shift = repo.open_shift(s, user.id)
        if shift is None:
            await _reply(update, T.SHIFT_NONE_OPEN, kb.main_menu(False, app_links()))
            return

        end_utc = tu.now_utc()
        if (end_utc - shift.start_utc) > dt.timedelta(hours=MAX_SHIFT_HOURS):
            await _reply(update, T.SHIFT_TOO_LONG, kb.main_menu(True, app_links()))
            return

        calendar = get_calendar(user.city)
        repo.close_shift(s, user, shift, end_utc, calendar)
        status = ceiling_mod.current_month_status(s, user)
        card = fmt.shift_card(shift, calendar, status)
        shift_id = shift.id
        alert = _ceiling_alert(s, user, status)

    await _reply(update, card, kb.after_shift(shift_id))
    if alert:
        await context.bot.send_message(
            update.effective_chat.id, alert, parse_mode=ParseMode.HTML
        )


def _ceiling_alert(s, user, status) -> str | None:
    """Emit a threshold warning at most once per threshold per month."""
    if not user.notify_ceiling:
        return None

    month_key = f"{status.year}-{status.month:02d}"
    if user.last_alert_month != month_key:
        user.last_alert_month = month_key
        user.last_alert_pct = 0

    threshold = ceiling_mod.crossed_threshold(status, user.last_alert_pct)
    if threshold is None:
        return None

    user.last_alert_pct = threshold
    s.flush()

    if status.over_ceiling:
        return T.ALERT_OVER_CEILING.format(
            earned=fmt.fmt_money(status.earned_agorot),
            ceiling=fmt.fmt_money(status.ceiling_agorot),
            over=fmt.fmt_money(-status.remaining_agorot),
        )
    return T.ALERT_CEILING.format(
        pct=threshold,
        remaining=fmt.fmt_money(status.remaining_agorot),
        hours=fmt.fmt_hours(status.remaining_base_hours),
    )


async def cb_cancel_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Discard an open shift without recording it — for a start pressed by
    mistake, which must not become a zero-length entry."""
    if not await guard(update, context):
        return
    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        shift = repo.open_shift(s, user.id)
        if shift is None:
            await _reply(update, T.SHIFT_NONE_OPEN, kb.main_menu(False, app_links()))
            return
        repo.delete_shift(s, shift)
    await _reply(update, T.SHIFT_CANCELLED, kb.main_menu(False, app_links()))


async def cmd_shift(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/shift toggles: it ends an open shift, otherwise starts one."""
    if not await guard(update, context):
        return
    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        has_open = repo.open_shift(s, user.id) is not None
    if has_open:
        await cb_stop(update, context)
    else:
        await cb_start(update, context)


# -------------------------------------------------------------------- listing

async def cb_month_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        months = repo.months_with_data(s, user.id)

    if not months:
        await _reply(update, T.NO_SHIFTS_AT_ALL, kb.back_only())
        return
    await _reply(update, "🗓 בחר חודש:", kb.month_list(months, None))


async def cb_shifts_of_month(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    _, year_s, month_s = update.callback_query.data.split(":")
    year, month = int(year_s), int(month_s)

    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        calendar = get_calendar(user.city)
        shifts = repo.shifts_in_month(s, user.id, year, month)
        status = ceiling_mod.month_status(s, user, year, month)

        if not shifts:
            await _reply(update, T.NO_SHIFTS_YET, kb.back_only())
            return

        lines = [fmt.rtl(f"🗓 <b>{fmt.fmt_month(year, month)}</b>"), ""]
        lines += [fmt.shift_line(sh, calendar) for sh in shifts]
        lines += ["", fmt.ceiling_block(status)]
        text = "\n".join(lines)
        markup = kb.shifts_in_month(shifts, year, month)

    await _reply(update, text, markup)


async def cb_shift_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    shift_id = int(update.callback_query.data.split(":")[1])

    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        shift = repo.get_shift(s, user.id, shift_id)
        if shift is None or shift.end_utc is None:
            await _reply(update, T.ERROR_GENERIC, kb.back_only())
            return
        calendar = get_calendar(user.city)
        local_start = tu.to_local(shift.start_utc)
        text = fmt.shift_card(shift, calendar, status=None, title="🗓 משמרת")
        back_to = f"ls:{local_start.year}:{local_start.month}"

    await _reply(update, text, kb.shift_detail(shift_id, back_to))


async def cb_delete_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    shift_id = int(update.callback_query.data.split(":")[1])

    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        shift = repo.get_shift(s, user.id, shift_id)
        if shift is None:
            await _reply(update, T.ERROR_GENERIC, kb.back_only())
            return
        calendar = get_calendar(user.city)
        summary = fmt.shift_line(shift, calendar)

    await _reply(update, T.CONFIRM_DELETE.format(summary=summary), kb.confirm_delete(shift_id))


async def cb_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    shift_id = int(update.callback_query.data.split(":")[1])

    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        shift = repo.get_shift(s, user.id, shift_id)
        if shift is not None:
            repo.delete_shift(s, shift)
            s.flush()
        status = ceiling_mod.current_month_status(s, user)
        text = T.SHIFT_DELETED + "\n\n" + fmt.ceiling_block(status)

    await _reply(update, text, main_menu_markup(update.effective_user.id))


async def cmd_undo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete the most recent closed shift, after confirming."""
    if not await guard(update, context):
        return
    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        recent = repo.recent_shifts(s, user.id, limit=1)
        if not recent:
            await _reply(update, T.NO_SHIFTS_AT_ALL, kb.back_only())
            return
        calendar = get_calendar(user.city)
        shift = recent[0]
        summary = fmt.shift_line(shift, calendar)
        shift_id = shift.id

    await _reply(update, T.CONFIRM_DELETE.format(summary=summary), kb.confirm_delete(shift_id))


def will_cross_ceiling_warning(status, extra_agorot: int) -> str | None:
    """Warn before hours are worked, not after they are logged."""
    if status.over_ceiling or status.hourly_agorot <= 0:
        return None
    if status.remaining_agorot - extra_agorot >= 0:
        return None
    hours_left = estimate_hours_for_amount(status.remaining_agorot, status.hourly_agorot)
    return T.ALERT_WILL_CROSS.format(hours=fmt.fmt_hours(hours_left))
