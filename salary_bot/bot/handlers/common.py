"""Shared handler infrastructure: authorisation, rendering, the main menu."""
from __future__ import annotations

import datetime as dt
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from ...config import DEFAULT_CITY, Config
from ...core import access, db, repo
from ...core import timeutil as tu
from ...core.calendar_service import CalendarService
from ...core.cities import get_city
from .. import formatting
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


def _bootstrap_ids() -> frozenset[int]:
    return CONFIG.allowed_user_ids if CONFIG else frozenset()


# How far ahead the Mini App is told about חג, so those days are marked before
# one is picked.
REST_LOOKAHEAD_DAYS = 120


def calendar_url() -> str | None:
    """The Mini App's address, or None when no HTTPS address is configured and
    the inline grid stands in for it.

    Deliberately needs neither a user nor a database read: it is called on
    every main-menu render, and which dates are חג is the same for everyone.
    """
    if CONFIG is None or not CONFIG.webapp_enabled:
        return None

    calendar = get_calendar(DEFAULT_CITY)
    today = tu.now_local().date()
    rest = [
        (today + dt.timedelta(days=offset)).isoformat()
        for offset in range(-31, REST_LOOKAHEAD_DAYS)
        if calendar.rest_kind(today + dt.timedelta(days=offset)) == "chag"
    ]
    return f"{CONFIG.webapp_url}/?rest={','.join(rest)}"


def reports_url() -> str | None:
    """The same page, opened on its reports view."""
    if CONFIG is None or not CONFIG.webapp_enabled:
        return None
    return f"{CONFIG.webapp_url}/?view=reports"


def app_links() -> kb.AppLinks:
    return kb.AppLinks(calendar=calendar_url(), reports=reports_url())


async def _send(update: Update, text: str, markup=None) -> None:
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            text, reply_markup=markup, parse_mode=ParseMode.HTML
        )
    elif update.message:
        await update.message.reply_text(
            text, reply_markup=markup, parse_mode=ParseMode.HTML
        )


async def guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """The single access gate. True means the handler may proceed.

    Someone with no access is not simply refused: a pending row is recorded and
    the admin is notified once, so a new user's first message becomes an access
    request they can act on rather than a dead end.
    """
    tg = update.effective_user
    if tg is None:
        return False

    with db.session_scope() as s:
        user = db.get_or_create_user(s, tg.id, tg.username, tg.first_name)
        access.apply_bootstrap(s, user, _bootstrap_ids())
        s.flush()

        if access.is_approved(user):
            return True

        status = user.status
        notify_targets: list[int] = []
        request_text = ""

        if status == access.PENDING and not user.access_notified:
            targets = access.admin_ids(s, _bootstrap_ids())
            # Never notify the requester about their own request.
            notify_targets = [t for t in targets if t != tg.id]
            request_text = T.ADMIN_ACCESS_REQUEST.format(
                name=access.display_name(user), id=tg.id
            )
            user.access_notified = True
            first_request = True
        else:
            first_request = False

    if status == access.DENIED:
        await _send(update, T.ACCESS_DENIED)
        log.warning("Blocked denied user %s", tg.id)
        return False

    await _send(
        update,
        (T.ACCESS_REQUESTED if first_request else T.ACCESS_PENDING).format(id=tg.id),
    )

    for admin_id in notify_targets:
        try:
            await context.bot.send_message(
                admin_id, request_text,
                reply_markup=kb.access_request(tg.id), parse_mode=ParseMode.HTML,
            )
        except Exception:
            log.exception("Could not deliver the access request to admin %s", admin_id)

    if first_request and not notify_targets:
        log.warning(
            "User %s requested access but there is no admin to notify. "
            "Add an ID to ALLOWED_USER_IDS and restart.", tg.id
        )
    return False


def is_admin(tg_user_id: int) -> bool:
    with db.session_scope() as s:
        return access.is_admin(s, tg_user_id)


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
    return kb.main_menu(has_open, app_links())


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
    if not await guard(update, context):
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
    if not await guard(update, context):
        return
    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        day_rate, night_rate = repo.effective_rates(s, user.id, dt.date.today())
    text = T.HELP.format(bands=formatting.bands_text(day_rate, night_rate))
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
