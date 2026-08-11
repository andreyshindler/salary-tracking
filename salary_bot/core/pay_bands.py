"""The pay rules: which rate applies when.

Pricing is a **band table** rather than one rate times a multiplier, because two
different base rates are in play. The day rate applies to ordinary daytime work
and to Shabbat/חג; the night rate applies to the overnight bands.

Daily bands (they tile a full 24 hours, so every minute is covered exactly once):

======================  ==========  ===========
window (local)          multiplier  base rate
======================  ==========  ===========
08:00 – 22:00           100%        day
22:00 – 05:00           100%        night
05:00 – 07:00           125%        night
07:00 – 08:00           200%        night
======================  ==========  ===========

Rest windows, which override the daily bands entirely for the hours they cover:

==========================================  ==========  ==========
window                                      multiplier  base rate
==========================================  ==========  ==========
Friday 20:00 → Saturday 20:00               150%        day
ערב חג 20:00 → חג 20:00                     200%        day
==========================================  ==========  ==========

Two readings that were not fully pinned down and are assumed here:

* **The chag window starts the evening before**, mirroring the Shabbat rule
  where Friday is the eve and the window covers the holy day itself. The
  alternative — starting at 20:00 *on* the chag and running into the following
  day — would place the premium a day later.
* **A rest window overrides the daily bands completely.** Saturday 05:00–07:00
  is 150% × day rate, not 125% × night rate. Where Shabbat and חג overlap, the
  higher multiplier wins.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from ..config import ISRAEL_TZ

DAY_RATE = "day"
NIGHT_RATE = "night"

# Rest windows run from 20:00 on the eve to 20:00 on the day itself.
REST_WINDOW_START_MIN = 20 * 60
REST_WINDOW_END_MIN = 20 * 60


@dataclass(frozen=True)
class Band:
    """A daily time band. ``start_min``/``end_min`` are minutes from local
    midnight; a band whose end is not after its start wraps midnight."""

    start_min: int
    end_min: int
    multiplier: float
    rate: str
    kind: str
    label: str

    def contains_minute(self, minute: float) -> bool:
        if self.start_min < self.end_min:
            return self.start_min <= minute < self.end_min
        return minute >= self.start_min or minute < self.end_min


DEFAULT_BANDS: tuple[Band, ...] = (
    Band(8 * 60, 22 * 60, 1.0, DAY_RATE, "day", "יום"),
    Band(22 * 60, 5 * 60, 1.0, NIGHT_RATE, "night", "לילה"),
    Band(5 * 60, 7 * 60, 1.25, NIGHT_RATE, "early", "לפנות בוקר"),
    Band(7 * 60, 8 * 60, 2.0, NIGHT_RATE, "dawn", "בוקר"),
)

REST_RULES: dict[str, tuple[float, str, str]] = {
    # calendar kind -> (multiplier, kind, label)
    "shabbat": (1.5, "shabbat", "שבת"),
    "chag": (2.0, "chag", "חג"),
}


@dataclass(frozen=True)
class RestWindow:
    start: dt.datetime      # aware UTC
    end: dt.datetime        # aware UTC
    multiplier: float
    kind: str
    label: str

    def contains(self, moment: dt.datetime) -> bool:
        return self.start <= moment < self.end


def band_at(moment_utc: dt.datetime, bands=DEFAULT_BANDS) -> Band:
    local = moment_utc.astimezone(ISRAEL_TZ)
    minute = local.hour * 60 + local.minute + local.second / 60
    for band in bands:
        if band.contains_minute(minute):
            return band
    raise AssertionError(f"the band table leaves {minute} uncovered")


def band_boundaries(start: dt.datetime, end: dt.datetime, bands=DEFAULT_BANDS) -> list[dt.datetime]:
    """Every daily-band edge in the span, as aware UTC.

    Built from local wall-clock times so a boundary stays at 08:00 on the clock
    regardless of the UTC offset in force that day.
    """
    day = start.astimezone(ISRAEL_TZ).date() - dt.timedelta(days=1)
    last = end.astimezone(ISRAEL_TZ).date() + dt.timedelta(days=1)

    minutes = {b.start_min for b in bands} | {b.end_min for b in bands}
    edges: list[dt.datetime] = []
    while day <= last:
        midnight = dt.datetime.combine(day, dt.time())
        for minute in minutes:
            local = (midnight + dt.timedelta(minutes=minute)).replace(tzinfo=ISRAEL_TZ)
            edges.append(local.astimezone(dt.timezone.utc))
        day += dt.timedelta(days=1)
    return edges


def rest_windows(calendar, start: dt.datetime, end: dt.datetime) -> list[RestWindow]:
    """Shabbat and חג windows overlapping the span.

    A window is anchored to the rest *day*: it opens at 20:00 the evening before
    and closes at 20:00 on the day itself.
    """
    first = start.astimezone(ISRAEL_TZ).date() - dt.timedelta(days=2)
    last = end.astimezone(ISRAEL_TZ).date() + dt.timedelta(days=2)

    windows: list[RestWindow] = []
    day = first
    while day <= last:
        kind = calendar.rest_kind(day)
        if kind is not None:
            multiplier, window_kind, label = REST_RULES[kind]
            eve = day - dt.timedelta(days=1)
            open_at = (
                dt.datetime.combine(eve, dt.time())
                + dt.timedelta(minutes=REST_WINDOW_START_MIN)
            ).replace(tzinfo=ISRAEL_TZ)
            close_at = (
                dt.datetime.combine(day, dt.time())
                + dt.timedelta(minutes=REST_WINDOW_END_MIN)
            ).replace(tzinfo=ISRAEL_TZ)
            window = RestWindow(
                start=open_at.astimezone(dt.timezone.utc),
                end=close_at.astimezone(dt.timezone.utc),
                multiplier=multiplier,
                kind=window_kind,
                label=label,
            )
            if window.start < end and window.end > start:
                windows.append(window)
        day += dt.timedelta(days=1)
    return sorted(windows, key=lambda w: w.start)


def rest_window_at(moment: dt.datetime, windows: list[RestWindow]) -> RestWindow | None:
    """The window covering an instant, highest multiplier first.

    Chag and Shabbat windows overlap whenever a holiday falls next to a
    Saturday, and the better-paying one applies.
    """
    covering = [w for w in windows if w.contains(moment)]
    if not covering:
        return None
    return max(covering, key=lambda w: w.multiplier)
