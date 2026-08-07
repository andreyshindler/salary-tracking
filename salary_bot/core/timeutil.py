"""Timezone helpers.

The rule throughout this codebase: **compute in UTC, display in Israel time.**

This is not pedantry. Adding a timedelta to a tz-aware Asia/Jerusalem datetime
does wall-clock arithmetic and produces a wrong offset across the DST switch,
which would make a shift on the changeover night come out an hour long or short.
Doing the arithmetic in UTC and converting only for display avoids that entirely.
"""
from __future__ import annotations

import datetime as dt

from ..config import ISRAEL_TZ


def now_utc() -> dt.datetime:
    """Current time as a naive UTC datetime (what we store)."""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def now_local() -> dt.datetime:
    """Current time as an aware Israel-local datetime (what we show)."""
    return dt.datetime.now(ISRAEL_TZ)


def to_utc_naive(aware: dt.datetime) -> dt.datetime:
    """Aware datetime -> naive UTC, for storage."""
    if aware.tzinfo is None:
        raise ValueError("expected a timezone-aware datetime")
    return aware.astimezone(dt.timezone.utc).replace(tzinfo=None)


def to_aware_utc(naive: dt.datetime) -> dt.datetime:
    """Naive UTC (as stored) -> aware UTC, for arithmetic."""
    if naive.tzinfo is not None:
        return naive.astimezone(dt.timezone.utc)
    return naive.replace(tzinfo=dt.timezone.utc)


def to_local(naive_utc: dt.datetime) -> dt.datetime:
    """Naive UTC (as stored) -> aware Israel local, for display."""
    return to_aware_utc(naive_utc).astimezone(ISRAEL_TZ)


def local_naive_to_utc(local_naive: dt.datetime) -> dt.datetime:
    """A wall-clock time the user typed -> naive UTC.

    ``fold=0`` resolves the ambiguous hour repeated at the autumn DST switch to
    the first (daylight-time) occurrence.
    """
    return to_utc_naive(local_naive.replace(tzinfo=ISRAEL_TZ, fold=0))


def local_date_of(naive_utc: dt.datetime) -> dt.date:
    return to_local(naive_utc).date()


def month_bounds_utc(year: int, month: int) -> tuple[dt.datetime, dt.datetime]:
    """[start, end) of a local calendar month, as naive UTC."""
    start_local = dt.datetime(year, month, 1)
    if month == 12:
        end_local = dt.datetime(year + 1, 1, 1)
    else:
        end_local = dt.datetime(year, month + 1, 1)
    return local_naive_to_utc(start_local), local_naive_to_utc(end_local)
