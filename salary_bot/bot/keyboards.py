"""Inline keyboards and the callback-data vocabulary.

Callback data is namespaced ``area:action[:arg]`` so main.py can route whole
areas with one regex each.
"""
from __future__ import annotations

from dataclasses import dataclass

from telegram import InlineKeyboardButton as Btn
from telegram import InlineKeyboardMarkup as Markup
from telegram import WebAppInfo

from ..core.cities import CITIES
from ..core.models import Shift
from . import texts_he as T
from .formatting import shift_button_label

CB_MAIN = "m:main"


@dataclass(frozen=True)
class AppLinks:
    """Mini App addresses, or None where it is not configured.

    Carried as one value so a menu built anywhere in the codebase offers the
    same buttons — an omitted link silently downgrades to the chat fallback,
    which is exactly the kind of difference nobody notices.
    """

    calendar: str | None = None
    reports: str | None = None


def _app_or_chat(label: str, url: str | None, callback: str) -> Btn:
    """A ``web_app`` button opens the app on the first tap, with no intermediate
    message to press through. Without an HTTPS address there is no app to open,
    and the button falls back to the in-chat version."""
    if url:
        return Btn(label, web_app=WebAppInfo(url=url))
    return Btn(label, callback_data=callback)


def calendar_button(calendar_url: str | None) -> Btn:
    return _app_or_chat(T.BTN_CALENDAR, calendar_url, "cal:today")


def main_menu(has_open_shift: bool, links: AppLinks = AppLinks()) -> Markup:
    """Hours are entered through the diary, so the menu offers no separate
    start-a-shift or type-it-by-hand buttons."""
    rows = [
        [calendar_button(links.calendar),
         Btn(T.BTN_STATUS, callback_data="st:cur")],
        [_app_or_chat(T.BTN_REPORTS, links.reports, "rep:menu"),
         Btn(T.BTN_SETTINGS, callback_data="set:menu")],
        [Btn(T.BTN_HELP, callback_data="help")],
    ]
    if links.reports is None:
        # The reports app lists the month's shifts and can delete one. Without
        # it there is no other way to reach an older shift, so the chat list
        # earns its place in the menu — and only then.
        rows.insert(1, [Btn(T.BTN_MY_SHIFTS, callback_data="ls:menu")])
    if has_open_shift:
        # A shift left running from before the start buttons went away still
        # has to be closable, so these appear only while one exists.
        rows.insert(0, [Btn(T.BTN_STOP_SHIFT, callback_data="sh:stop"),
                        Btn(T.BTN_CANCEL_SHIFT, callback_data="sh:cancel")])
    return Markup(rows)


def open_webapp(calendar_url: str) -> Markup:
    """For /calendar, where there is no menu button to attach the app to."""
    return Markup([
        [Btn(T.BTN_OPEN_WEBAPP, web_app=WebAppInfo(url=calendar_url))],
        [Btn(T.BTN_BACK, callback_data=CB_MAIN)],
    ])


def back_only() -> Markup:
    return Markup([[Btn(T.BTN_BACK, callback_data=CB_MAIN)]])


def after_shift(shift_id: int) -> Markup:
    """Edit/delete offered directly on the breakdown card, so fixing a typo
    never means navigating back through the menu."""
    return Markup([
        [Btn(T.BTN_EDIT, callback_data=f"sd:{shift_id}"),
         Btn(T.BTN_DELETE, callback_data=f"del:{shift_id}")],
        [Btn(T.BTN_BACK, callback_data=CB_MAIN)],
    ])


def confirm_delete(shift_id: int) -> Markup:
    return Markup([
        [Btn(T.BTN_CONFIRM_DELETE, callback_data=f"delok:{shift_id}")],
        [Btn(T.BTN_CANCEL, callback_data=f"sd:{shift_id}")],
    ])


def shift_detail(shift_id: int, back_to: str) -> Markup:
    return Markup([
        [Btn(T.BTN_DELETE, callback_data=f"del:{shift_id}")],
        [Btn(T.BTN_BACK, callback_data=back_to)],
    ])


def month_list(months: list[tuple[int, int]], current: tuple[int, int] | None) -> Markup:
    from .formatting import fmt_month

    rows = []
    for year, month in months[:12]:
        label = fmt_month(year, month)
        if current == (year, month):
            label = f"• {label}"
        rows.append([Btn(label, callback_data=f"ls:{year}:{month}")])
    rows.append([Btn(T.BTN_BACK, callback_data=CB_MAIN)])
    return Markup(rows)


def shifts_in_month(shifts: list[Shift], year: int, month: int) -> Markup:
    rows = [
        [Btn(shift_button_label(sh), callback_data=f"sd:{sh.id}")]
        for sh in shifts
    ]
    rows.append([Btn(T.BTN_BACK, callback_data="ls:menu")])
    return Markup(rows)


def reports_menu() -> Markup:
    return Markup([
        [Btn(T.BTN_REP_MONTH, callback_data="rep:month")],
        [Btn(T.BTN_REP_TIERS, callback_data="rep:tiers")],
        [Btn(T.BTN_REP_FORECAST, callback_data="rep:fc")],
        [Btn(T.BTN_REP_YEAR, callback_data="rep:year")],
        [Btn(T.BTN_REP_CSV, callback_data="rep:csv")],
        [Btn(T.BTN_BACK, callback_data=CB_MAIN)],
    ])


def settings_menu(is_admin: bool = False, pending_count: int = 0) -> Markup:
    rows = [
        [Btn(T.BTN_SET_RATE, callback_data="set:rate"),
         Btn(T.BTN_SET_CEILING, callback_data="set:ceil")],
        [Btn(T.BTN_SET_OT, callback_data="set:ot")],
        [Btn(T.BTN_SET_NOTIF, callback_data="set:notif")],
        [Btn(T.BTN_SET_BACKUP, callback_data="set:backup")],
    ]
    if is_admin:
        # Surface the count so waiting requests are visible without opening it.
        label = T.BTN_USERS + (f" ({pending_count})" if pending_count else "")
        rows.append([Btn(label, callback_data="acc:list")])
    rows.append([Btn(T.BTN_BACK, callback_data=CB_MAIN)])
    return Markup(rows)


def city_picker(current: str) -> Markup:
    rows = []
    row: list[Btn] = []
    for key, city in CITIES.items():
        label = f"• {city.name_he}" if key == current else city.name_he
        row.append(Btn(label, callback_data=f"setcity:{key}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([Btn(T.BTN_BACK, callback_data="set:menu")])
    return Markup(rows)


def overtime_menu(apply_overtime: bool) -> Markup:
    toggle_label = "🔕 כבה חישוב תוספות" if apply_overtime else "🔔 הפעל חישוב תוספות"
    rows = [[Btn(toggle_label, callback_data="set:ottoggle")]]
    rows.append([Btn(T.BTN_RECALC, callback_data="set:recalc")])
    rows.append([Btn(T.BTN_BACK, callback_data="set:menu")])
    return Markup(rows)


def notifications_menu(open_shift: bool, ceiling: bool, month: bool) -> Markup:
    def mark(on: bool, label: str) -> str:
        return f"{'✅' if on else '⬜️'} {label}"

    return Markup([
        [Btn(mark(open_shift, T.NOTIF_OPEN_SHIFT), callback_data="notif:open")],
        [Btn(mark(ceiling, T.NOTIF_CEILING), callback_data="notif:ceiling")],
        [Btn(mark(month, T.NOTIF_MONTH), callback_data="notif:month")],
        [Btn(T.BTN_BACK, callback_data="set:menu")],
    ])


def onboarding(needs_rate: bool) -> Markup:
    rows = []
    if needs_rate:
        rows.append([Btn(T.BTN_SET_RATE, callback_data="set:rate")])
    rows.append([Btn(T.BTN_BACK, callback_data=CB_MAIN)])
    return Markup(rows)


def cancel_only() -> Markup:
    return Markup([[Btn(T.BTN_CANCEL, callback_data=CB_MAIN)]])


# ------------------------------------------------------------ access control

def access_request(tg_user_id: int) -> Markup:
    """Approve/deny straight from the notification, so a request needs no
    navigation to act on."""
    return Markup([[
        Btn(T.BTN_APPROVE, callback_data=f"acc:ok:{tg_user_id}"),
        Btn(T.BTN_DENY, callback_data=f"acc:no:{tg_user_id}"),
    ]])


def users_menu(pending: list, approved: list) -> Markup:
    """Pending requests first — they are the only rows needing a decision."""
    rows = []
    for user in pending:
        label = _user_label(user)
        rows.append([
            Btn(f"✅ {label}", callback_data=f"acc:ok:{user.tg_user_id}"),
            Btn("❌", callback_data=f"acc:no:{user.tg_user_id}"),
        ])
    for user in approved:
        label = _user_label(user)
        mark = "👑" if user.is_admin else "👤"
        rows.append([Btn(f"{mark} {label}", callback_data=f"acc:show:{user.tg_user_id}")])
    rows.append([Btn(T.BTN_BACK, callback_data="set:menu")])
    return Markup(rows)


def user_detail(tg_user_id: int, is_self: bool) -> Markup:
    rows = []
    # Revoking your own access would lock you out of the bot with no way back
    # except editing the environment, so it is not offered.
    if not is_self:
        rows.append([Btn(T.BTN_REVOKE, callback_data=f"acc:rev:{tg_user_id}")])
    rows.append([Btn(T.BTN_BACK, callback_data="acc:list")])
    return Markup(rows)


def _user_label(user) -> str:
    from ..core.access import display_name

    return display_name(user)
