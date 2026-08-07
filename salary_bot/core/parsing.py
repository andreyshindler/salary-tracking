"""Parsing of free-text user input.

Manual entry is deliberately a typed line rather than a chain of inline-button
pickers: "אתמול 16:00 21:30" is one message, where a date picker plus two time
pickers is a dozen taps. Buttons still exist for the common cases; this is the
fast path.
"""
from __future__ import annotations

import datetime as dt
import re

TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
DATE_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b")

RELATIVE_DAYS = {
    "היום": 0,
    "אתמול": -1,
    "שלשום": -2,
}


class ParseError(ValueError):
    """Raised with a Hebrew, user-facing message."""


def parse_amount(text: str) -> int:
    """Parse a shekel amount into agorot.

    Accepts "85", "85.5", "₪85", "10,113". A comma followed by exactly three
    digits is a thousands separator; otherwise it is treated as a decimal point,
    since both conventions turn up in practice.
    """
    cleaned = text.strip().replace("₪", "").replace("שח", "").replace('ש"ח', "").strip()
    cleaned = re.sub(r"(?<=\d),(?=\d{3}\b)", "", cleaned)  # thousands separator
    cleaned = cleaned.replace(",", ".")
    cleaned = re.sub(r"\s+", "", cleaned)

    if not re.fullmatch(r"\d+(\.\d+)?", cleaned):
        raise ParseError("לא הצלחתי להבין את הסכום. שלח מספר, למשל: 85 או 85.5")

    value = float(cleaned)
    if value < 0 or value > 1_000_000:
        raise ParseError("הסכום נראה לא סביר. שלח מספר בשקלים, למשל: 85")
    return round(value * 100)


def parse_hours(text: str) -> float:
    cleaned = text.strip().replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d+)?", cleaned):
        raise ParseError("שלח מספר שעות, למשל: 8 או 8.6")
    value = float(cleaned)
    if not 0 < value <= 24:
        raise ParseError("מספר השעות חייב להיות בין 0 ל‑24.")
    return value


def parse_time_of_day(text: str, on_date: dt.date) -> dt.datetime:
    """Parse a bare "HH:MM" into a naive local datetime on a given date."""
    match = TIME_RE.search(text.strip())
    if not match:
        raise ParseError("שלח שעה בפורמט HH:MM, למשל: 16:00")
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise ParseError("השעה לא תקינה. שלח שעה בפורמט HH:MM, למשל: 16:00")
    return dt.datetime(on_date.year, on_date.month, on_date.day, hour, minute)


def parse_manual_entry(text: str, today: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """Parse a whole shift from one line into naive local (start, end).

    Accepted shapes::

        16:00 21:30              -> today
        16:00-21:30              -> today
        אתמול 16:00 21:30        -> yesterday
        12/09 16:00 21:30        -> 12 September of the current year
        12/09/2026 16:00 21:30   -> explicit year

    An end at or before the start is read as crossing midnight, so
    "22:00 04:00" is a six-hour overnight shift rather than an error.
    """
    raw = text.strip()
    if not raw:
        raise ParseError("לא קיבלתי טקסט.")

    normalised = raw.replace("–", "-").replace("—", "-").replace("־", "-")

    work_date = today
    for word, delta in RELATIVE_DAYS.items():
        if word in normalised:
            work_date = today + dt.timedelta(days=delta)
            normalised = normalised.replace(word, " ")
            break
    else:
        date_match = DATE_RE.search(normalised)
        if date_match:
            day, month = int(date_match.group(1)), int(date_match.group(2))
            year_part = date_match.group(3)
            if year_part is None:
                year = today.year
            else:
                year = int(year_part)
                if year < 100:
                    year += 2000
            try:
                work_date = dt.date(year, month, day)
            except ValueError:
                raise ParseError("התאריך לא תקין. נסה למשל: 12/09 16:00 21:30")
            normalised = normalised[: date_match.start()] + " " + normalised[date_match.end():]

    times = TIME_RE.findall(normalised)
    if len(times) < 2:
        raise ParseError(
            "צריך שתי שעות — התחלה וסיום.\nלמשל: 16:00 21:30\nאו: אתמול 16:00 21:30"
        )
    if len(times) > 2:
        raise ParseError("מצאתי יותר משתי שעות. שלח רק שעת התחלה ושעת סיום.")

    (sh, sm), (eh, em) = times[0], times[1]
    sh, sm, eh, em = int(sh), int(sm), int(eh), int(em)
    if sh > 23 or eh > 23 or sm > 59 or em > 59:
        raise ParseError("אחת השעות לא תקינה. שלח בפורמט HH:MM.")

    start = dt.datetime(work_date.year, work_date.month, work_date.day, sh, sm)
    end = dt.datetime(work_date.year, work_date.month, work_date.day, eh, em)
    if end <= start:
        end += dt.timedelta(days=1)  # overnight shift

    if (end - start) > dt.timedelta(hours=24):
        raise ParseError("משמרת ארוכה מ‑24 שעות. בדוק את השעות.")

    return start, end
