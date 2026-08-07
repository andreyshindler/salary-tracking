"""Inline keyboards and the callback-data vocabulary.

Callback data is namespaced ``area:action[:arg]`` so main.py can route whole
areas with one regex each.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton as Btn
from telegram import InlineKeyboardMarkup as Markup

from ..core.cities import CITIES
from ..core.models import Shift
from . import texts_he as T
from .formatting import shift_button_label

CB_MAIN = "m:main"


def main_menu(has_open_shift: bool) -> Markup:
    """The open-shift button replaces the start button rather than sitting
    beside it — only one of the two is ever a valid action."""
    toggle = (
        Btn(T.BTN_STOP_SHIFT, callback_data="sh:stop")
        if has_open_shift
        else Btn(T.BTN_START_SHIFT, callback_data="sh:start")
    )
    rows = [
        [toggle, Btn(T.BTN_MANUAL, callback_data="man:new")],
        [Btn(T.BTN_STATUS, callback_data="st:cur")],
        [Btn(T.BTN_MY_SHIFTS, callback_data="ls:menu"), Btn(T.BTN_REPORTS, callback_data="rep:menu")],
        [Btn(T.BTN_SETTINGS, callback_data="set:menu"), Btn(T.BTN_HELP, callback_data="help")],
    ]
    if has_open_shift:
        rows.insert(1, [Btn(T.BTN_CANCEL_SHIFT, callback_data="sh:cancel")])
    else:
        rows[0].insert(1, Btn(T.BTN_START_EARLIER, callback_data="sh:earlier"))
    return Markup(rows)


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


def settings_menu() -> Markup:
    return Markup([
        [Btn(T.BTN_SET_RATE, callback_data="set:rate"),
         Btn(T.BTN_SET_CEILING, callback_data="set:ceil")],
        [Btn(T.BTN_SET_CITY, callback_data="set:city")],
        [Btn(T.BTN_SET_OT, callback_data="set:ot")],
        [Btn(T.BTN_SET_NOTIF, callback_data="set:notif")],
        [Btn(T.BTN_SET_BACKUP, callback_data="set:backup")],
        [Btn(T.BTN_BACK, callback_data=CB_MAIN)],
    ])


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


def overtime_menu(apply_overtime: bool, threshold: float) -> Markup:
    toggle_label = "🔕 כבה חישוב שעות נוספות" if apply_overtime else "🔔 הפעל חישוב שעות נוספות"
    rows = [[Btn(toggle_label, callback_data="set:ottoggle")]]
    if apply_overtime:
        rows.append([Btn(f"⏱ סף יומי: {threshold:g} שעות", callback_data="set:otthr")])
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
    rows.append([Btn(T.BTN_SET_CITY, callback_data="set:city")])
    rows.append([Btn(T.BTN_BACK, callback_data=CB_MAIN)])
    return Markup(rows)


def cancel_only() -> Markup:
    return Markup([[Btn(T.BTN_CANCEL, callback_data=CB_MAIN)]])
