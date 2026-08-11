"""Pricing a shift into rate segments.

This is the correctness-critical module. A shift is not ``hours × rate``: both
the multiplier *and* the base rate change with the clock, so the shift is cut at
every point where either changes and each piece is priced on its own.

The rules themselves live in :mod:`pay_bands`. Here we only cut, classify and
multiply. Two structural points:

* **Rest windows override the daily bands.** Inside Shabbat or חג the whole
  stretch takes the rest rate; the daily bands resume when the window closes.
* All arithmetic is in **aware UTC**, while band edges are built from Israel
  local wall-clock time. A shift crossing the DST change is billed the real
  number of hours, and 08:00 still means 08:00 on the clock.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .calendar_service import CalendarService
from .pay_bands import (
    DAY_RATE, DEFAULT_BANDS, band_at, band_boundaries, rest_window_at, rest_windows,
)


@dataclass(frozen=True)
class PricedSegment:
    start: dt.datetime          # aware UTC
    end: dt.datetime            # aware UTC
    hours: float
    multiplier: float
    rate_agorot: int            # the base rate this piece was priced at
    kind: str                   # day | night | early | dawn | shabbat | chag
    reason: str                 # Hebrew label
    amount_agorot: int


@dataclass(frozen=True)
class PricedShift:
    start: dt.datetime
    end: dt.datetime
    total_hours: float
    total_agorot: int
    segments: list[PricedSegment]


def _merge_adjacent(segments: list[PricedSegment]) -> list[PricedSegment]:
    """Collapse touching segments priced identically.

    Band edges inside a rest window would otherwise split one continuous 150%
    stretch into several identical-looking rows, which reads as a mistake.
    """
    merged: list[PricedSegment] = []
    for seg in segments:
        prev = merged[-1] if merged else None
        if (
            prev is not None
            and prev.end == seg.start
            and prev.kind == seg.kind
            and prev.multiplier == seg.multiplier
            and prev.rate_agorot == seg.rate_agorot
        ):
            merged[-1] = PricedSegment(
                start=prev.start,
                end=seg.end,
                hours=prev.hours + seg.hours,
                multiplier=prev.multiplier,
                rate_agorot=prev.rate_agorot,
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
    day_agorot: int,
    night_agorot: int,
    calendar: CalendarService,
    bands=DEFAULT_BANDS,
    apply_premiums: bool = True,
) -> PricedShift:
    """Split a shift at every rate change and price each piece.

    ``start`` and ``end`` must be aware datetimes; they are normalised to UTC.
    ``apply_premiums=False`` prices everything flat at the day rate.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("price_shift requires timezone-aware datetimes")

    start = start.astimezone(dt.timezone.utc)
    end = end.astimezone(dt.timezone.utc)
    if end <= start:
        raise ValueError("shift end must be after its start")

    rates = {DAY_RATE: day_agorot, "night": night_agorot}

    if not apply_premiums:
        hours = (end - start).total_seconds() / 3600.0
        segment = PricedSegment(
            start=start, end=end, hours=hours, multiplier=1.0,
            rate_agorot=day_agorot, kind="day", reason="",
            amount_agorot=round(hours * day_agorot),
        )
        return PricedShift(start, end, round(hours, 6), segment.amount_agorot, [segment])

    windows = rest_windows(calendar, start, end)

    # 1. Boundaries: shift edges, rest-window edges, and daily band edges.
    points = {start, end}
    edges = [e for w in windows for e in (w.start, w.end)]
    edges += band_boundaries(start, end, bands)
    points.update(e for e in edges if start < e < end)
    ordered = sorted(points)

    # 2. Classify and price each piece: a rest window wins over the daily band.
    segments: list[PricedSegment] = []
    for left, right in zip(ordered, ordered[1:]):
        midpoint = left + (right - left) / 2

        window = rest_window_at(midpoint, windows)
        if window is not None:
            multiplier, kind, reason = window.multiplier, window.kind, window.label
            rate_agorot = rates[DAY_RATE]
        else:
            band = band_at(midpoint, bands)
            multiplier, kind, reason = band.multiplier, band.kind, band.label
            rate_agorot = rates[band.rate]

        hours = (right - left).total_seconds() / 3600.0
        segments.append(
            PricedSegment(
                start=left,
                end=right,
                hours=hours,
                multiplier=multiplier,
                rate_agorot=rate_agorot,
                kind=kind,
                reason=reason,
                amount_agorot=round(hours * multiplier * rate_agorot),
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
    """How many hours at a given rate and multiplier are worth ``amount_agorot``.

    Used to turn "you have 3,693 NIS of headroom left" into "that is about 98
    ordinary hours", which is the form the user can actually act on.
    """
    if hourly_agorot <= 0 or multiplier <= 0:
        return 0.0
    return max(0.0, amount_agorot / (hourly_agorot * multiplier))
