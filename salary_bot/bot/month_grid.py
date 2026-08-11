"""The calendar month grid.

Laid out **right to left**: the first column of each row is Saturday and the
last is Sunday, so the grid reads the way a Hebrew wall calendar does, with
ראשון on the right. Telegram renders keyboard columns left to right and will
not mirror them, so the reversal has to be done here.

Every cell needs a callback, including the blank padding ones, hence ``noop``.
"""
from __future__ import annotations

import calendar as pycalendar
import datetime as dt

from telegram import InlineKeyboardButton as Btn
from telegram import InlineKeyboardMarkup as Markup

from . import texts_he as T

# Right to left, so the row reads ראשון .. שבת from the right.
WEEKDAY_HEADERS_RTL = ["ש", "ו", "ה", "ד", "ג", "ב", "א"]

MARK_LOGGED = "•"
MARK_CHAG = "✡"


def _weeks(year: int, month: int) -> list[list[int | None]]:
    """Weeks as Sunday-first rows, with None padding outside the month."""
    cal = pycalendar.Calendar(firstweekday=6)  # 6 = Sunday
    return [
        [day if day != 0 else None for day in week]
        for week in cal.monthdayscalendar(year, month)
    ]


def day_label(
    day: int, *, has_shifts: bool, is_chag: bool, is_today: bool
) -> str:
    """Compact enough for a seven-column keyboard: five characters at most."""
    label = str(day)
    if is_chag:
        label += MARK_CHAG
    if has_shifts:
        label = MARK_LOGGED + label
    if is_today:
        label = f"[{label}]"
    return label


def month_grid(
    year: int,
    month: int,
    logged_days: dict[int, int],
    chag_days: set[int],
    today: dt.date | None = None,
) -> Markup:
    rows: list[list[Btn]] = [
        [Btn(header, callback_data="noop") for header in WEEKDAY_HEADERS_RTL]
    ]

    for week in _weeks(year, month):
        row = []
        for day in week:
            if day is None:
                row.append(Btn(" ", callback_data="noop"))
                continue
            row.append(Btn(
                day_label(
                    day,
                    has_shifts=day in logged_days,
                    is_chag=day in chag_days,
                    is_today=today is not None
                    and (today.year, today.month, today.day) == (year, month, day),
                ),
                callback_data=f"cal:d:{year}:{month}:{day}",
            ))
        rows.append(list(reversed(row)))  # right-to-left

    previous = dt.date(year, month, 1) - dt.timedelta(days=1)
    following = dt.date(year, month, pycalendar.monthrange(year, month)[1]) + dt.timedelta(days=1)
    rows.append([
        Btn("▶️", callback_data=f"cal:m:{following.year}:{following.month}"),
        Btn(T.BTN_TODAY, callback_data="cal:today"),
        Btn("◀️", callback_data=f"cal:m:{previous.year}:{previous.month}"),
    ])
    rows.append([Btn(T.BTN_BACK, callback_data="m:main")])
    return Markup(rows)


def day_menu(day: dt.date, shifts: list) -> Markup:
    from .formatting import shift_button_label

    rows = [[Btn(T.BTN_ADD_HOURS, callback_data=f"cal:add:{day.year}:{day.month}:{day.day}")]]
    rows += [[Btn(shift_button_label(sh), callback_data=f"sd:{sh.id}")] for sh in shifts]
    rows.append([Btn(T.BTN_BACK, callback_data=f"cal:m:{day.year}:{day.month}")])
    return Markup(rows)
