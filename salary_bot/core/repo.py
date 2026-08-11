"""Data access: shift CRUD and the versioned rate/ceiling lookups."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from .calendar_service import CalendarService
from .models import Ceiling, Rate, Shift, ShiftSegment, User
from .pay_engine import price_shift
from . import timeutil as tu


# ------------------------------------------------------------ rate / ceiling

def effective_rate(s: Session, user_id: int, on: dt.date) -> int:
    """Hourly rate in agorot in force on a date — the latest one that had
    already taken effect. Never the current rate for an old shift."""
    row = s.execute(
        select(Rate)
        .where(Rate.user_id == user_id, Rate.effective_from <= on)
        .order_by(Rate.effective_from.desc())
        .limit(1)
    ).scalar_one_or_none()
    return row.hourly_agorot if row else 0


def effective_ceiling(s: Session, user_id: int, on: dt.date) -> int:
    row = s.execute(
        select(Ceiling)
        .where(Ceiling.user_id == user_id, Ceiling.effective_from <= on)
        .order_by(Ceiling.effective_from.desc())
        .limit(1)
    ).scalar_one_or_none()
    return row.amount_agorot if row else 0


def set_rate(s: Session, user_id: int, agorot: int, effective_from: dt.date) -> None:
    existing = s.execute(
        select(Rate).where(Rate.user_id == user_id, Rate.effective_from == effective_from)
    ).scalar_one_or_none()
    if existing:
        existing.hourly_agorot = agorot
    else:
        s.add(Rate(user_id=user_id, hourly_agorot=agorot, effective_from=effective_from))


def set_ceiling(s: Session, user_id: int, agorot: int, effective_from: dt.date) -> None:
    existing = s.execute(
        select(Ceiling).where(
            Ceiling.user_id == user_id, Ceiling.effective_from == effective_from
        )
    ).scalar_one_or_none()
    if existing:
        existing.amount_agorot = agorot
    else:
        s.add(Ceiling(user_id=user_id, amount_agorot=agorot, effective_from=effective_from))


# -------------------------------------------------------------------- shifts

def open_shift(s: Session, user_id: int) -> Shift | None:
    return s.execute(
        select(Shift)
        .where(Shift.user_id == user_id, Shift.end_utc.is_(None))
        .order_by(Shift.start_utc.desc())
        .limit(1)
    ).scalar_one_or_none()


def overlapping_shift(
    s: Session, user_id: int, start_utc: dt.datetime, end_utc: dt.datetime,
    exclude_id: int | None = None,
) -> Shift | None:
    """A closed shift already covering part of this interval.

    Double-logging the same hours would quietly inflate the monthly total, which
    is exactly the number the user relies on, so entries are rejected rather
    than merged.
    """
    stmt = select(Shift).where(
        Shift.user_id == user_id,
        Shift.end_utc.is_not(None),
        Shift.start_utc < end_utc,
        Shift.end_utc > start_utc,
    )
    if exclude_id is not None:
        stmt = stmt.where(Shift.id != exclude_id)
    return s.execute(stmt.limit(1)).scalar_one_or_none()


def start_shift(s: Session, user_id: int, start_utc: dt.datetime) -> Shift:
    shift = Shift(
        user_id=user_id,
        start_utc=start_utc,
        end_utc=None,
        work_date=tu.local_date_of(start_utc),
        source="live",
    )
    s.add(shift)
    s.flush()
    return shift


def price_and_store(s: Session, user: User, shift: Shift, calendar: CalendarService) -> Shift:
    """(Re)price a closed shift and replace its stored segments."""
    if shift.end_utc is None:
        raise ValueError("cannot price a shift that has not ended")

    rate = effective_rate(s, user.id, tu.local_date_of(shift.start_utc))
    priced = price_shift(
        start=tu.to_aware_utc(shift.start_utc),
        end=tu.to_aware_utc(shift.end_utc),
        hourly_agorot=rate,
        calendar=calendar,
        night_start_min=user.night_start_min,
        night_end_min=user.night_end_min,
        apply_premiums=user.apply_overtime,
    )

    # Mutate the relationship rather than inserting rows with a raw shift_id:
    # the delete-orphan cascade only knows about children it can see in the
    # collection, and a stale collection means deleting the shift later fails
    # on the foreign key.
    shift.segments.clear()
    s.flush()

    for seg in priced.segments:
        shift.segments.append(
            ShiftSegment(
                from_utc=seg.start.replace(tzinfo=None),
                to_utc=seg.end.replace(tzinfo=None),
                hours=seg.hours,
                multiplier=seg.multiplier,
                kind=seg.kind,
                reason=seg.reason,
                amount_agorot=seg.amount_agorot,
            )
        )

    shift.total_agorot = priced.total_agorot
    shift.work_date = tu.local_date_of(shift.start_utc)
    s.flush()
    return shift


def close_shift(
    s: Session, user: User, shift: Shift, end_utc: dt.datetime, calendar: CalendarService
) -> Shift:
    shift.end_utc = end_utc
    return price_and_store(s, user, shift, calendar)


def add_manual_shift(
    s: Session, user: User, start_utc: dt.datetime, end_utc: dt.datetime,
    calendar: CalendarService, note: str | None = None,
) -> Shift:
    shift = Shift(
        user_id=user.id,
        start_utc=start_utc,
        end_utc=end_utc,
        work_date=tu.local_date_of(start_utc),
        note=note,
        source="manual",
    )
    s.add(shift)
    s.flush()
    return price_and_store(s, user, shift, calendar)


def reprice_all(s: Session, user: User, calendar: CalendarService) -> int:
    """Re-price every closed shift under the current rules; returns the count.

    Segments are stored rather than recomputed on read, which is what makes
    reports auditable — but it also means a change to the pay rules leaves old
    shifts carrying the totals they were priced at. When the rules themselves
    were wrong, that is a correction the user has to be able to apply.
    """
    shifts = list(
        s.execute(
            select(Shift).where(Shift.user_id == user.id, Shift.end_utc.is_not(None))
        ).scalars()
    )
    for shift in shifts:
        price_and_store(s, user, shift, calendar)
    return len(shifts)


def shifts_in_month(s: Session, user_id: int, year: int, month: int) -> list[Shift]:
    """Closed shifts attributed to a local calendar month.

    Attribution is by the shift's *start*, so a shift running past midnight on
    the last of the month counts entirely to the month it began in — matching
    how the user thinks about the day he worked.
    """
    start_utc, end_utc = tu.month_bounds_utc(year, month)
    return list(
        s.execute(
            select(Shift)
            .where(
                Shift.user_id == user_id,
                Shift.end_utc.is_not(None),
                Shift.start_utc >= start_utc,
                Shift.start_utc < end_utc,
            )
            .order_by(Shift.start_utc)
        ).scalars()
    )


def recent_shifts(s: Session, user_id: int, limit: int = 10) -> list[Shift]:
    return list(
        s.execute(
            select(Shift)
            .where(Shift.user_id == user_id, Shift.end_utc.is_not(None))
            .order_by(Shift.start_utc.desc())
            .limit(limit)
        ).scalars()
    )


def get_shift(s: Session, user_id: int, shift_id: int) -> Shift | None:
    return s.execute(
        select(Shift).where(Shift.id == shift_id, Shift.user_id == user_id)
    ).scalar_one_or_none()


def delete_shift(s: Session, shift: Shift) -> None:
    s.delete(shift)


def months_with_data(s: Session, user_id: int) -> list[tuple[int, int]]:
    """(year, month) pairs that have at least one shift, newest first."""
    rows = s.execute(
        select(Shift.work_date).where(
            Shift.user_id == user_id, Shift.end_utc.is_not(None)
        )
    ).scalars()
    seen = {(d.year, d.month) for d in rows}
    return sorted(seen, reverse=True)
