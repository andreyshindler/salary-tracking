"""Pricing a shift into rate segments.

This is the correctness-critical module. A shift is not ``hours × rate``: the
same hour is worth a different amount depending on when it falls, so the shift
is cut into segments at every point where the rate changes, and each segment is
priced on its own.

Rate table (Israeli hourly practice):

===============  ======  ======  ======
                 base    +2h OT  beyond
===============  ======  ======  ======
ordinary day     100%    125%    150%
rest day / chag  150%    175%    200%
===============  ======  ======  ======

Two structural choices:

* Overtime accumulates **across the whole shift**, not per calendar date. A
  shift running 22:00-04:00 is one working day, and its ninth hour is overtime
  regardless of midnight falling in the middle. Consequently midnight is not a
  segment boundary — only rate changes are, which also keeps the breakdown card
  readable.
* All arithmetic is in **aware UTC**. A shift crossing the DST change is then
  automatically the right number of real hours.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .calendar_service import CalendarService

EPS = 1e-9

MULTIPLIERS: dict[str, dict[str, float]] = {
    "regular": {"base": 1.0, "ot1": 1.25, "ot2": 1.5},
    "rest": {"base": 1.5, "ot1": 1.75, "ot2": 2.0},
}


@dataclass(frozen=True)
class PricedSegment:
    start: dt.datetime          # aware UTC
    end: dt.datetime            # aware UTC
    hours: float
    multiplier: float
    kind: str                   # regular | rest
    tier: str                   # base | ot1 | ot2
    reason: str                 # Hebrew label, e.g. "שבת"
    amount_agorot: int


@dataclass(frozen=True)
class PricedShift:
    start: dt.datetime
    end: dt.datetime
    total_hours: float
    total_agorot: int
    segments: list[PricedSegment]


def _tier_at(cum_hours: float, t1: float, t2: float, apply_overtime: bool) -> tuple[str, float]:
    """Which tier the next hour falls into, and the cumulative-hours limit
    at which that tier ends."""
    if not apply_overtime:
        return "base", float("inf")
    if cum_hours < t1 - EPS:
        return "base", t1
    if cum_hours < t2 - EPS:
        return "ot1", t2
    return "ot2", float("inf")


def price_shift(
    start: dt.datetime,
    end: dt.datetime,
    hourly_agorot: int,
    calendar: CalendarService,
    daily_ot_threshold: float = 8.0,
    ot1_span: float = 2.0,
    apply_overtime: bool = True,
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

    # 1. Boundaries: shift edges, plus every rest-block edge falling inside.
    blocks = calendar.rest_blocks_overlapping(start, end)
    points = {start, end}
    for block in blocks:
        for edge in (block.start, block.end):
            if start < edge < end:
                points.add(edge)
    ordered = sorted(points)

    t1 = daily_ot_threshold
    t2 = daily_ot_threshold + ot1_span

    segments: list[PricedSegment] = []
    cum_hours = 0.0

    # 2. Walk each interval, subdividing again wherever an overtime tier ends.
    for left, right in zip(ordered, ordered[1:]):
        midpoint = left + (right - left) / 2
        kind = "regular"
        reason = ""
        for block in blocks:
            if block.contains(midpoint):
                kind, reason = "rest", block.label
                break

        cursor = left
        while (right - cursor).total_seconds() > EPS:
            remaining = (right - cursor).total_seconds() / 3600.0
            tier, limit = _tier_at(cum_hours, t1, t2, apply_overtime)
            available = float("inf") if limit == float("inf") else limit - cum_hours
            take = min(remaining, available)

            nxt = cursor + dt.timedelta(hours=take)
            if nxt > right:
                nxt = right
            take = (nxt - cursor).total_seconds() / 3600.0

            multiplier = MULTIPLIERS[kind][tier]
            segments.append(
                PricedSegment(
                    start=cursor,
                    end=nxt,
                    hours=take,
                    multiplier=multiplier,
                    kind=kind,
                    tier=tier,
                    reason=reason,
                    amount_agorot=round(take * multiplier * hourly_agorot),
                )
            )
            cum_hours += take
            cursor = nxt

    return PricedShift(
        start=start,
        end=end,
        total_hours=round(cum_hours, 6),
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
