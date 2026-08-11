"""Pricing a shift into rate segments.

This is the correctness-critical module. A shift is not ``hours × rate``: the
same hour is worth a different amount depending on *when* it falls, so the shift
is cut into segments at every point where the rate changes and each segment is
priced on its own.

There are exactly **two rates**:

======================================  ======
night (22:00-08:00), Shabbat, or חג     150%
everything else                         100%
======================================  ======

Three consequences worth stating, because each is a decision rather than an
accident:

* **There is no overtime by hours worked.** A twelve-hour day shift is 100%
  throughout. Length of shift never changes the rate — only the clock and the
  calendar do.
* **Premiums do not stack.** An hour that is both night *and* Shabbat is 150%,
  not 200%. There are only two rates, so the highest that can ever apply is
  150%.
* All arithmetic is in **aware UTC**, and the night window is evaluated in
  Israel local time. A shift crossing the DST change is therefore billed the
  real number of hours, while 22:00 still means 22:00 on the clock.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from ..config import ISRAEL_TZ
from .calendar_service import CalendarService

EPS = 1e-9

BASE_MULTIPLIER = 1.0
PREMIUM_MULTIPLIER = 1.5

# Minutes from local midnight. 22:00 and 08:00.
DEFAULT_NIGHT_START_MIN = 22 * 60
DEFAULT_NIGHT_END_MIN = 8 * 60

NIGHT_LABEL = "לילה"

KIND_REGULAR = "regular"
KIND_REST = "rest"
KIND_NIGHT = "night"


@dataclass(frozen=True)
class PricedSegment:
    start: dt.datetime          # aware UTC
    end: dt.datetime            # aware UTC
    hours: float
    multiplier: float
    kind: str                   # regular | rest | night
    reason: str                 # Hebrew label, e.g. "שבת" or "לילה"
    amount_agorot: int


@dataclass(frozen=True)
class PricedShift:
    start: dt.datetime
    end: dt.datetime
    total_hours: float
    total_agorot: int
    segments: list[PricedSegment]


def _minutes_of_day(moment_utc: dt.datetime) -> float:
    local = moment_utc.astimezone(ISRAEL_TZ)
    return local.hour * 60 + local.minute + local.second / 60


def is_night(
    moment_utc: dt.datetime,
    night_start_min: int = DEFAULT_NIGHT_START_MIN,
    night_end_min: int = DEFAULT_NIGHT_END_MIN,
) -> bool:
    """Whether an instant falls in the night window, in Israel local time."""
    if night_start_min == night_end_min:
        return False  # an empty window disables the premium
    minutes = _minutes_of_day(moment_utc)
    if night_start_min > night_end_min:
        # The usual case: the window wraps midnight (22:00 -> 08:00).
        return minutes >= night_start_min or minutes < night_end_min
    return night_start_min <= minutes < night_end_min


def _night_boundaries(
    start: dt.datetime, end: dt.datetime, night_start_min: int, night_end_min: int
) -> list[dt.datetime]:
    """Every night-window edge in the span, as aware UTC.

    Built from *local* wall-clock times and then converted, so the boundary sits
    at 22:00 on the clock regardless of the UTC offset in force that day.
    """
    if night_start_min == night_end_min:
        return []

    day = start.astimezone(ISRAEL_TZ).date() - dt.timedelta(days=1)
    last = end.astimezone(ISRAEL_TZ).date() + dt.timedelta(days=1)

    edges: list[dt.datetime] = []
    while day <= last:
        midnight = dt.datetime.combine(day, dt.time())
        for minutes in {night_start_min, night_end_min}:
            local = (midnight + dt.timedelta(minutes=minutes)).replace(tzinfo=ISRAEL_TZ)
            edges.append(local.astimezone(dt.timezone.utc))
        day += dt.timedelta(days=1)
    return edges


def _merge_adjacent(segments: list[PricedSegment]) -> list[PricedSegment]:
    """Collapse touching segments priced identically.

    A night boundary inside Shabbat would otherwise split one 150% stretch into
    two identical-looking rows on the breakdown card, which reads as a mistake.
    """
    merged: list[PricedSegment] = []
    for seg in segments:
        prev = merged[-1] if merged else None
        if (
            prev is not None
            and prev.end == seg.start
            and prev.kind == seg.kind
            and prev.multiplier == seg.multiplier
            and prev.reason == seg.reason
        ):
            merged[-1] = PricedSegment(
                start=prev.start,
                end=seg.end,
                hours=prev.hours + seg.hours,
                multiplier=prev.multiplier,
                kind=prev.kind,
                reason=prev.reason,
                amount_agorot=prev.amount_agorot + seg.amount_agorot,
            )
        else:
            merged.append(seg)
    return merged


def price_shift(
    start: dt.datetime,
    end: dt.datetime,
    hourly_agorot: int,
    calendar: CalendarService,
    night_start_min: int = DEFAULT_NIGHT_START_MIN,
    night_end_min: int = DEFAULT_NIGHT_END_MIN,
    apply_premiums: bool = True,
) -> PricedShift:
    """Split a shift at every rate change and price each piece.

    ``start`` and ``end`` must be aware datetimes; they are normalised to UTC.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("price_shift requires timezone-aware datetimes")

    start = start.astimezone(dt.timezone.utc)
    end = end.astimezone(dt.timezone.utc)
    if end <= start:
        raise ValueError("shift end must be after its start")

    blocks = calendar.rest_blocks_overlapping(start, end) if apply_premiums else []

    # 1. Boundaries: the shift edges, every rest-block edge, and every night
    #    edge falling strictly inside.
    points = {start, end}
    if apply_premiums:
        edges = [e for b in blocks for e in (b.start, b.end)]
        edges += _night_boundaries(start, end, night_start_min, night_end_min)
        points.update(e for e in edges if start < e < end)
    ordered = sorted(points)

    # 2. Classify and price each piece. Rest beats night only for the label;
    #    both carry the same multiplier, so nothing stacks.
    segments: list[PricedSegment] = []
    for left, right in zip(ordered, ordered[1:]):
        midpoint = left + (right - left) / 2

        kind, reason = KIND_REGULAR, ""
        if apply_premiums:
            block = next((b for b in blocks if b.contains(midpoint)), None)
            if block is not None:
                kind, reason = KIND_REST, block.label
            elif is_night(midpoint, night_start_min, night_end_min):
                kind, reason = KIND_NIGHT, NIGHT_LABEL

        multiplier = BASE_MULTIPLIER if kind == KIND_REGULAR else PREMIUM_MULTIPLIER
        hours = (right - left).total_seconds() / 3600.0
        segments.append(
            PricedSegment(
                start=left,
                end=right,
                hours=hours,
                multiplier=multiplier,
                kind=kind,
                reason=reason,
                amount_agorot=round(hours * multiplier * hourly_agorot),
            )
        )

    segments = _merge_adjacent(segments)
    total_hours = sum(s.hours for s in segments)

    return PricedShift(
        start=start,
        end=end,
        total_hours=round(total_hours, 6),
        total_agorot=sum(s.amount_agorot for s in segments),
        segments=segments,
    )


def estimate_hours_for_amount(
    amount_agorot: int, hourly_agorot: int, multiplier: float = 1.0
) -> float:
    """How many hours at a given multiplier are worth ``amount_agorot``.

    Used to turn "you have 3,693 NIS of headroom left" into "that is about 36.9
    ordinary hours", which is the form the user can actually act on.
    """
    if hourly_agorot <= 0 or multiplier <= 0:
        return 0.0
    return max(0.0, amount_agorot / (hourly_agorot * multiplier))
