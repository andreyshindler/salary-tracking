"""Settings: rate, ceiling, city, overtime rules, notifications, backup."""
from __future__ import annotations

import io
import sqlite3
import tempfile
from pathlib import Path

from telegram import InputFile, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...core import access, db, repo
from ...core import ceiling as ceiling_mod
from ...core import timeutil as tu
from ...core.cities import get_city
from ...core.parsing import (
    ParseError, format_minutes, parse_amount, parse_night_window,
)
from .. import formatting as fmt
from .. import keyboards as kb
from .. import texts_he as T
from . import common
from .common import clear_awaiting, guard, safe_edit, set_awaiting



async def _reply(update: Update, text: str, markup=None) -> None:
    if update.callback_query:
        await update.callback_query.answer()
        await safe_edit(update.callback_query, text, markup)
    else:
        await update.message.reply_text(
            text, reply_markup=markup, parse_mode=ParseMode.HTML
        )


def _settings_markup(tg_user_id: int):
    """Settings keyboard, with the user-management entry only for admins."""
    with db.session_scope() as s:
        admin = access.is_admin(s, tg_user_id)
        pending = len(access.users_by_status(s, access.PENDING)) if admin else 0
    return kb.settings_menu(admin, pending)


def _night_label(user) -> str:
    return f"{format_minutes(user.night_start_min)}–{format_minutes(user.night_end_min)}"


def _summary(s, user) -> str:
    today = tu.now_local().date()
    rate = repo.effective_rate(s, user.id, today)
    ceiling_agorot = repo.effective_ceiling(s, user.id, today)
    ot = T.OT_ON.format(night=_night_label(user)) if user.apply_overtime else T.OT_OFF
    body = T.SETTINGS_SUMMARY.format(
        rate=f"{fmt.fmt_money(rate)} לשעה" if rate > 0 else "לא הוגדר",
        ceiling=fmt.fmt_money(ceiling_agorot),
        city=get_city(user.city).name_he,
        ot=ot,
    )
    return f"<b>{T.SETTINGS_TITLE}</b>\n\n" + "\n".join(fmt.rtl(line) for line in body.splitlines())


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    clear_awaiting(context)
    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        text = _summary(s, user)
    await _reply(update, text, _settings_markup(update.effective_user.id))


# ------------------------------------------------------------- value prompts

async def cb_ask_rate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    set_awaiting(context, "rate")
    await _reply(update, T.ASK_RATE, kb.cancel_only())


async def cb_ask_ceiling(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    set_awaiting(context, "ceiling")
    await _reply(update, T.ASK_CEILING, kb.cancel_only())


async def cb_ask_night_window(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    set_awaiting(context, "night_window")
    await _reply(update, T.ASK_NIGHT_WINDOW, kb.cancel_only())


async def handle_rate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        agorot = parse_amount(update.message.text)
    except ParseError as exc:
        await update.message.reply_text(str(exc), reply_markup=kb.cancel_only())
        return
    if agorot <= 0:
        await update.message.reply_text("התעריף חייב להיות גדול מאפס.", reply_markup=kb.cancel_only())
        return

    # Effective from the first of the current month, so this month prices
    # consistently while earlier months keep the rate they were logged at.
    today = tu.now_local().date()
    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        repo.set_rate(s, user.id, agorot, today.replace(day=1))

    clear_awaiting(context)
    await update.message.reply_text(
        T.RATE_SAVED.format(rate=fmt.fmt_money(agorot)),
        reply_markup=_settings_markup(update.effective_user.id), parse_mode=ParseMode.HTML,
    )


async def handle_ceiling(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        agorot = parse_amount(update.message.text)
    except ParseError as exc:
        await update.message.reply_text(str(exc), reply_markup=kb.cancel_only())
        return
    if agorot <= 0:
        await update.message.reply_text("התקרה חייבת להיות גדולה מאפס.", reply_markup=kb.cancel_only())
        return

    today = tu.now_local().date()
    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        repo.set_ceiling(s, user.id, agorot, today.replace(day=1))

    clear_awaiting(context)
    await update.message.reply_text(
        T.CEILING_SAVED.format(ceiling=fmt.fmt_money(agorot)),
        reply_markup=_settings_markup(update.effective_user.id), parse_mode=ParseMode.HTML,
    )


async def handle_night_window(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        start_min, end_min = parse_night_window(update.message.text)
    except ParseError as exc:
        await update.message.reply_text(str(exc), reply_markup=kb.cancel_only())
        return

    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        user.night_start_min = start_min
        user.night_end_min = end_min
        s.flush()
        label = _night_label(user)

    clear_awaiting(context)
    await update.message.reply_text(
        T.NIGHT_WINDOW_SAVED.format(night=label) + "\n\n" + T.RECALC_HINT,
        reply_markup=_settings_markup(update.effective_user.id), parse_mode=ParseMode.HTML,
    )


# ---------------------------------------------------------------------- city

async def cb_city_picker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        current = user.city
    await _reply(update, T.ONBOARD_NEED_CITY, kb.city_picker(current))


async def cb_set_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    city_key = update.callback_query.data.split(":")[1]
    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        user.city = city_key
        s.flush()
        text = T.CITY_SAVED.format(city=get_city(city_key).name_he) + "\n\n" + _summary(s, user)
    await _reply(update, text, _settings_markup(update.effective_user.id))


# ------------------------------------------------------- premiums / night hours

def _premium_text(user) -> str:
    return fmt.rtl(
        "🌙 <b>תוספות שכר</b>\n\n"
        "יש שני תעריפים בלבד:\n"
        f"‏• <b>150%</b> — לילה ({_night_label(user)}), שבת וחג\n"
        "‏• <b>100%</b> — כל השאר\n\n"
        "אורך המשמרת לא משנה את התעריף. שעה שהיא גם לילה וגם שבת "
        "נשארת 150% — התוספות לא מצטברות.\n\n"
        "אם השכר שלך משולם בתעריף אחיד, אפשר לכבות את החישוב."
    )


async def cb_overtime_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        text, apply_ot, label = _premium_text(user), user.apply_overtime, _night_label(user)
    await _reply(update, text, kb.overtime_menu(apply_ot, label))


async def cb_toggle_overtime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        user.apply_overtime = not user.apply_overtime
        s.flush()
        now_on, label = user.apply_overtime, _night_label(user)
    text = (T.OT_TOGGLED_ON if now_on else T.OT_TOGGLED_OFF) + "\n\n" + T.RECALC_HINT
    await _reply(update, text, kb.overtime_menu(now_on, label))


async def cb_recalculate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Re-price every stored shift under the current rules.

    Stored segments are what makes reports auditable, but it means a rules
    change leaves old shifts on the old numbers — and those numbers feed the
    ceiling. This is the correction.
    """
    if not await guard(update, context):
        return

    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        calendar = common.get_calendar(user.city)
        count = repo.reprice_all(s, user, calendar)
        if count == 0:
            await _reply(update, T.RECALC_NONE, _settings_markup(update.effective_user.id))
            return
        status = ceiling_mod.current_month_status(s, user)
        text = T.RECALC_DONE.format(count=count, ceiling=fmt.ceiling_block(status))

    await _reply(update, text, _settings_markup(update.effective_user.id))


# ------------------------------------------------------------- notifications

async def cb_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        flags = (user.notify_open_shift, user.notify_ceiling, user.notify_month_summary)
    await _reply(update, T.NOTIF_TITLE, kb.notifications_menu(*flags))


async def cb_toggle_notification(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    which = update.callback_query.data.split(":")[1]
    field = {
        "open": "notify_open_shift",
        "ceiling": "notify_ceiling",
        "month": "notify_month_summary",
    }[which]

    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        setattr(user, field, not getattr(user, field))
        s.flush()
        flags = (user.notify_open_shift, user.notify_ceiling, user.notify_month_summary)
    await _reply(update, T.NOTIF_TITLE, kb.notifications_menu(*flags))


# ------------------------------------------------------------------- backup

async def cb_backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a consistent copy of the database.

    Uses sqlite3's online backup API rather than copying the file: with WAL
    enabled, a plain copy can catch the database mid-write and arrive corrupt.
    """
    if not await guard(update, context):
        return
    await update.callback_query.answer()

    if common.CONFIG is None:
        await _reply(update, T.ERROR_GENERIC, _settings_markup(update.effective_user.id))
        return

    source_path = Path(common.CONFIG.db_path)
    with tempfile.TemporaryDirectory() as tmpdir:
        snapshot = Path(tmpdir) / "salary-backup.db"
        source = sqlite3.connect(str(source_path))
        target = sqlite3.connect(str(snapshot))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        data = snapshot.read_bytes()

    stamp = tu.now_local().strftime("%Y-%m-%d")
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=InputFile(io.BytesIO(data), filename=f"salary-backup-{stamp}.db"),
        caption=T.BACKUP_CAPTION,
    )
