"""Monthly aggregation against the exemption ceiling.

This is the number the whole bot exists to produce: how much room is left before
the month's earnings reach the ceiling, expressed both in shekels and — more
usefully — in hours the user can still work.
"""
from __future__ import annotations

import calendar as pycalendar
import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from . import repo
from . import timeutil as tu
from .models import User
from .pay_engine import estimate_hours_for_amount

# Percentages the user is warned at, in ascending order.
ALERT_THRESHOLDS = (80, 90, 100)


@dataclass
class TierTotal:
    multiplier: float
    kind: str
    hours: float = 0.0
    agorot: int = 0


@dataclass
class MonthStatus:
    year: int
    month: int
    earned_agorot: int
    ceiling_agorot: int
    total_hours: float
    shift_count: int
    hourly_agorot: int
    tiers: list[TierTotal] = field(default_factory=list)

    @property
    def remaining_agorot(self) -> int:
        return self.ceiling_agorot - self.earned_agorot

    @property
    def over_ceiling(self) -> bool:
        return self.earned_agorot > self.ceiling_agorot

    @property
    def pct(self) -> float:
        if self.ceiling_agorot <= 0:
            return 0.0
        return 100.0 * self.earned_agorot / self.ceiling_agorot

    @property
    def remaining_base_hours(self) -> float:
        """Headroom expressed as ordinary (100%) hours."""
        return estimate_hours_for_amount(
            max(0, self.remaining_agorot), self.hourly_agorot, 1.0
        )

    @property
    def remaining_rest_hours(self) -> float:
        """Headroom expressed as Shabbat/holiday (150%) hours — the same money
        buys fewer of them, which is the point worth surfacing."""
        return estimate_hours_for_amount(
            max(0, self.remaining_agorot), self.hourly_agorot, 1.5
        )

    def projected_crossing_date(self, today: dt.date | None = None) -> dt.date | None:
        """Date the ceiling would be crossed if the current pace continues.

        Returns None when the pace is zero, when the ceiling is already crossed,
        or when the pace would not reach it before the month ends.
        """
        today = today or tu.now_local().date()
        if today.year != self.year or today.month != self.month:
            return None
        if self.earned_agorot <= 0 or self.remaining_agorot <= 0:
            return None

        days_elapsed = today.day
        days_in_month = pycalendar.monthrange(self.year, self.month)[1]
        per_day = self.earned_agorot / days_elapsed
        if per_day <= 0:
            return None

        days_needed = self.remaining_agorot / per_day
        crossing_day = days_elapsed + days_needed
        if crossing_day > days_in_month:
            return None
        return dt.date(self.year, self.month, min(days_in_month, int(round(crossing_day)) or 1))


def month_status(s: Session, user: User, year: int, month: int) -> MonthStatus:
    shifts = repo.shifts_in_month(s, user.id, year, month)

    reference_day = dt.date(year, month, 1)
    ceiling_agorot = repo.effective_ceiling(s, user.id, reference_day)
    hourly_agorot = repo.effective_rate(s, user.id, tu.now_local().date())

    buckets: dict[tuple[str, float], TierTotal] = {}
    earned = 0
    total_hours = 0.0

    for shift in shifts:
        earned += shift.total_agorot
        for seg in shift.segments:
            total_hours += seg.hours
            key = (seg.kind, seg.multiplier)
            bucket = buckets.get(key)
            if bucket is None:
                bucket = TierTotal(multiplier=seg.multiplier, kind=seg.kind)
                buckets[key] = bucket
            bucket.hours += seg.hours
            bucket.agorot += seg.amount_agorot

    tiers = sorted(buckets.values(), key=lambda t: (t.kind != "regular", t.multiplier))

    return MonthStatus(
        year=year,
        month=month,
        earned_agorot=earned,
        ceiling_agorot=ceiling_agorot,
        total_hours=round(total_hours, 4),
        shift_count=len(shifts),
        hourly_agorot=hourly_agorot,
        tiers=tiers,
    )


def current_month_status(s: Session, user: User) -> MonthStatus:
    today = tu.now_local().date()
    return month_status(s, user, today.year, today.month)


def crossed_threshold(status: MonthStatus, already_alerted_pct: int) -> int | None:
    """Highest alert threshold newly reached, or None.

    Returns the threshold so the caller can record it and avoid re-warning about
    the same one on every subsequent shift.
    """
    pct = status.pct
    for threshold in reversed(ALERT_THRESHOLDS):
        if pct >= threshold and already_alerted_pct < threshold:
            return threshold
    return None
