"""Shared handler infrastructure: authorisation, rendering, the main menu."""
from __future__ import annotations

import datetime as dt
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from ...config import Config
from ...core import db, repo
from ...core.calendar_service import CalendarService
from ...core.cities import get_city
from .. import keyboards as kb
from .. import texts_he as T

log = logging.getLogger(__name__)

CONFIG: Config | None = None

# CalendarService keeps an in-process cache of resolved zmanim, so reusing one
# per city is what makes repeated month renders cheap.
_CALENDARS: dict[str, CalendarService] = {}


def set_config(config: Config) -> None:
    global CONFIG
    CONFIG = config


def get_calendar(city_key: str) -> CalendarService:
    cal = _CALENDARS.get(city_key)
    if cal is None:
        cal = CalendarService(city_key)
        _CALENDARS[city_key] = cal
    return cal


def is_authorised(user_id: int) -> bool:
    if CONFIG is None:
        return False
    return user_id in CONFIG.allowed_user_ids


async def reject(update: Update) -> None:
    """Deny access, but hand back the Telegram user ID.

    An empty allowlist locks everyone out, including the owner on first run, and
    the ID is the one thing they need to unlock it — so it is echoed here rather
    than making them hunt for it in the logs.
    """
    user_id = update.effective_user.id if update.effective_user else "?"
    text = f"{T.NOT_AUTHORISED}\n\nהמזהה שלך: <code>{user_id}</code>"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text, parse_mode=ParseMode.HTML)
    elif update.message:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    log.warning("Rejected message from unauthorised user %s", user_id)


async def safe_edit(query, text: str, markup=None) -> None:
    """Edit a message, tolerating Telegram's 'message is not modified' error,
    which fires whenever a user re-taps the button they are already on."""
    try:
        await query.edit_message_text(
            text, reply_markup=markup, parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise


def clear_awaiting(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("awaiting", None)
    context.user_data.pop("awaiting_arg", None)


def set_awaiting(context: ContextTypes.DEFAULT_TYPE, kind: str, arg=None) -> None:
    context.user_data["awaiting"] = kind
    context.user_data["awaiting_arg"] = arg


def main_menu_markup(tg_user_id: int):
    with db.session_scope() as s:
        user = db.get_or_create_user(s, tg_user_id)
        has_open = repo.open_shift(s, user.id) is not None
    return kb.main_menu(has_open)


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_awaiting(context)
    tg_id = update.effective_user.id
    markup = main_menu_markup(tg_id)

    if update.callback_query:
        await update.callback_query.answer()
        await safe_edit(update.callback_query, T.MAIN_MENU_TITLE, markup)
    else:
        await update.message.reply_text(
            T.MAIN_MENU_TITLE, reply_markup=markup, parse_mode=ParseMode.HTML
        )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update.effective_user.id):
        await reject(update)
        return

    tg_id = update.effective_user.id
    with db.session_scope() as s:
        user = db.get_or_create_user(s, tg_id)
        rate = repo.effective_rate(s, user.id, dt.date.today())
        needs_rate = rate <= 0

    if needs_rate:
        await update.message.reply_text(
            T.WELCOME, reply_markup=kb.onboarding(needs_rate=True), parse_mode=ParseMode.HTML
        )
        return

    await show_main_menu(update, context)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update.effective_user.id):
        await reject(update)
        return
    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        threshold = f"{user.daily_ot_threshold:g}"
    text = T.HELP.format(thr=threshold)
    if update.callback_query:
        await update.callback_query.answer()
        await safe_edit(update.callback_query, text, kb.back_only())
    else:
        await update.message.reply_text(
            text, reply_markup=kb.back_only(), parse_mode=ParseMode.HTML
        )


async def cb_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_main_menu(update, context)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Unhandled error while processing update", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(update.effective_chat.id, T.ERROR_GENERIC)
        except Exception:  # the notification itself must never mask the original error
            log.exception("Failed to deliver the error notice")


def city_name(city_key: str) -> str:
    return get_city(city_key).name_he
