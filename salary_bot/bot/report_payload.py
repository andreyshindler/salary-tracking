"""The numbers behind 📈 דוחות, shaped for the Mini App.

Formatting stays on this side. The page shows strings it is handed rather than
reimplementing shekel and hour rules in JavaScript, so "how money reads" has
one definition and the app and the chat cards cannot drift apart.

Nothing here touches Telegram or HTTP: it takes a session and returns a plain
dict, which is what makes it straightforward to assert against.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..core import ceiling as ceiling_mod
from ..core import repo
from ..core import timeutil as tu
from ..core.calendar_service import CalendarService
from ..core.models import User
from . import formatting as fmt


def month_label(year: int, month: int) -> dict:
    return {"year": year, "month": month, "label": fmt.fmt_month(year, month)}


def _shift_row(shift, calendar: CalendarService) -> dict:
    work_date = tu.to_local(shift.start_utc).date()
    hours = sum(seg.hours for seg in shift.segments)
    return {
        "id": shift.id,
        "date": work_date.strftime("%d.%m"),
        "day": fmt.day_name(work_date),
        "span": fmt.time_span(shift.start_utc, shift.end_utc),
        "hours": fmt.fmt_hours(hours),
        "amount": fmt.fmt_money(shift.total_agorot),
        "note": calendar.holiday_label(work_date),
    }


def month_report(s: Session, user: User, calendar: CalendarService,
                 year: int, month: int) -> dict:
    status = ceiling_mod.month_status(s, user, year, month)
    crossing = status.projected_crossing_date()

    return {
        **month_label(year, month),
        "earned": fmt.fmt_money(status.earned_agorot),
        "ceiling": fmt.fmt_money(status.ceiling_agorot),
        "remaining": fmt.fmt_money(abs(status.remaining_agorot)),
        "overCeiling": status.over_ceiling,
        # Capped for the bar only: a month at 130% must not draw past the end.
        "pct": round(min(100.0, max(0.0, status.pct)), 1),
        "pctLabel": f"{round(status.pct)}%",
        "hours": fmt.fmt_hours(status.total_hours),
        "shiftCount": status.shift_count,
        "remainingBaseHours": fmt.fmt_hours(status.remaining_base_hours),
        "remainingRestHours": fmt.fmt_hours(status.remaining_rest_hours),
        "crossingDate": crossing.strftime("%d.%m.%Y") if crossing else None,
        "needsRate": status.hourly_agorot <= 0,
        "tiers": [
            {
                "pct": fmt.fmt_pct(tier.multiplier),
                "label": fmt.kind_label(tier.kind),
                "hours": fmt.fmt_hours(tier.hours),
                "amount": fmt.fmt_money(tier.agorot),
            }
            for tier in status.tiers
        ],
        "shifts": [
            _shift_row(shift, calendar)
            for shift in repo.shifts_in_month(s, user.id, year, month)
        ],
    }


def year_report(s: Session, user: User, year: int) -> dict:
    rows = []
    earned_total = 0
    hours_total = 0.0
    for month in range(1, 13):
        status = ceiling_mod.month_status(s, user, year, month)
        if not status.shift_count:
            continue
        earned_total += status.earned_agorot
        hours_total += status.total_hours
        rows.append({
            **month_label(year, month),
            "short": fmt.fmt_month(year, month).rsplit(" ", 1)[0],
            "hours": fmt.fmt_hours(status.total_hours),
            "earned": fmt.fmt_money(status.earned_agorot),
            "pctLabel": f"{round(status.pct)}%",
            "overCeiling": status.over_ceiling,
        })

    return {
        "year": year,
        "rows": rows,
        "earned": fmt.fmt_money(earned_total),
        "hours": fmt.fmt_hours(hours_total),
    }


def build(s: Session, user: User, calendar: CalendarService,
          year: int | None = None, month: int | None = None) -> dict:
    """Everything the reports view needs for one render."""
    today = tu.now_local().date()
    year = year or today.year
    month = month or today.month
    # A month the user asks for but has never worked is a valid thing to look
    # at — it simply comes back empty rather than being refused.
    known = repo.months_with_data(s, user.id)
    if (today.year, today.month) not in known:
        known = [(today.year, today.month)] + list(known)
    if (year, month) not in known:
        known = sorted(set(known) | {(year, month)}, reverse=True)

    return {
        "months": [month_label(y, m) for y, m in sorted(known, reverse=True)],
        "month": month_report(s, user, calendar, year, month),
        "year": year_report(s, user, year),
    }


def parse_month(body: dict) -> tuple[int | None, int | None]:
    """Read a requested month out of an untrusted request body."""
    try:
        year = int(body["year"])
        month = int(body["month"])
    except (KeyError, TypeError, ValueError):
        return None, None
    # Anything outside this is a broken or tampered request, not a month
    # someone is looking at.
    if not (2000 <= year <= 2100 and 1 <= month <= 12):
        return None, None
    return year, month
