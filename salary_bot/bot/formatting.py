"""Rendering values and records into the Hebrew message bodies."""
from __future__ import annotations

import datetime as dt

from ..core import timeutil as tu
from ..core.calendar_service import CalendarService
from ..core.ceiling import MonthStatus
from ..core.models import Shift
from .texts_he import RLM

DAY_NAMES_HE = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
MONTH_NAMES_HE = [
    "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
    "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר",
]


def rtl(line: str) -> str:
    """Force RTL paragraph direction so lines starting with digits lay out right."""
    return f"{RLM}{line}"


def fmt_money(agorot: int) -> str:
    """Agorot -> a shekel string. Whole amounts drop the decimals, which is
    almost always the case and reads far better in a summary."""
    sign = "-" if agorot < 0 else ""
    value = abs(agorot) / 100
    if abs(value - round(value)) < 0.005:
        return f"{sign}₪{round(value):,}"
    return f"{sign}₪{value:,.2f}"


def fmt_hours(hours: float) -> str:
    if abs(hours - round(hours)) < 0.005:
        return str(int(round(hours)))
    return f"{hours:.2f}".rstrip("0").rstrip(".")


def fmt_pct(multiplier: float) -> str:
    return f"{round(multiplier * 100)}%"


KIND_LABELS_HE = {
    "day": "יום", "night": "לילה", "early": "לפנות בוקר", "dawn": "בוקר",
    "shabbat": "שבת", "chag": "חג",
    # Kinds written by earlier versions, kept so old rows still render.
    "regular": "רגיל", "rest": "שבת/חג",
}


SEGMENT_ICONS = {
    "shabbat": "🕯", "chag": "🕯", "rest": "🕯",
    "night": "🌙", "early": "🌙", "dawn": "🌅",
}


def kind_label(kind: str) -> str:
    return KIND_LABELS_HE.get(kind, kind)


def bands_text(day_agorot: int, night_agorot: int) -> str:
    """The rate table with the user's own rates filled in."""
    from ..core.pay_bands import DAY_RATE, DEFAULT_BANDS, REST_RULES
    from ..core.parsing import format_minutes

    rates = {DAY_RATE: day_agorot, "night": night_agorot}
    lines = [
        rtl(f"• {format_minutes(b.start_min)}–{format_minutes(b.end_min)} · "
            f"<b>{fmt_pct(b.multiplier)}</b> × {fmt_money(rates[b.rate])} ({b.label})")
        for b in DEFAULT_BANDS
    ]
    lines.append("")
    lines.append(rtl(f"• שישי 20:00 → שבת 20:00 · "
                     f"<b>{fmt_pct(REST_RULES['shabbat'][0])}</b> × {fmt_money(day_agorot)}"))
    lines.append(rtl(f"• ערב חג 20:00 → חג 20:00 · "
                     f"<b>{fmt_pct(REST_RULES['chag'][0])}</b> × {fmt_money(day_agorot)}"))
    return "\n".join(lines)


def day_name(day: dt.date) -> str:
    return DAY_NAMES_HE[day.weekday()]


def fmt_date(day: dt.date) -> str:
    return f"{day_name(day)}, {day.strftime('%d.%m.%Y')}"


def fmt_month(year: int, month: int) -> str:
    return f"{MONTH_NAMES_HE[month - 1]} {year}"


def progress_bar(pct: float, width: int = 20) -> str:
    filled = max(0, min(width, round(width * pct / 100)))
    return "▓" * filled + "░" * (width - filled)


def _local_hhmm(naive_utc: dt.datetime) -> str:
    return tu.to_local(naive_utc).strftime("%H:%M")


def _span(from_utc: dt.datetime, to_utc: dt.datetime) -> str:
    """A time range, carrying the end date when it falls on another day.

    Without it a Shabbat window renders as "20:00–20:00", which reads as a
    mistake rather than as twenty-four hours.
    """
    start, end = tu.to_local(from_utc), tu.to_local(to_utc)
    if start.date() == end.date():
        return f"{start:%H:%M}–{end:%H:%M}"
    return f"{start:%H:%M}–{end:%H:%M} ({end:%d.%m})"


# ------------------------------------------------------------------ shift card

def shift_breakdown(shift: Shift, calendar: CalendarService) -> str:
    """The per-segment breakdown — the part that shows the reasoning rather
    than just a total."""
    lines: list[str] = []
    for seg in shift.segments:
        rate = f" × {fmt_money(seg.rate_agorot)}" if seg.rate_agorot else ""
        pieces = [
            f"• {fmt_pct(seg.multiplier)}{rate}",
            _span(seg.from_utc, seg.to_utc),
            f"{fmt_hours(seg.hours)} ש׳",
            fmt_money(seg.amount_agorot),
        ]
        line = " · ".join(pieces)
        icon = SEGMENT_ICONS.get(seg.kind)
        if icon and seg.reason:
            line += f"  {icon} {seg.reason}"
        lines.append(rtl(line))
    return "\n".join(lines)


def shift_card(shift: Shift, calendar: CalendarService, status: MonthStatus | None = None,
               title: str = "✅ נרשמה משמרת") -> str:
    start_local = tu.to_local(shift.start_utc)
    end_local = tu.to_local(shift.end_utc)
    total_hours = sum(s.hours for s in shift.segments)

    holiday = calendar.holiday_label(start_local.date())
    header = f"<b>{title}</b> — {fmt_date(start_local.date())}"
    if holiday:
        header += f"  ({holiday})"

    lines = [
        rtl(header),
        rtl(f"🕐 {_span(shift.start_utc, shift.end_utc)} · "
            f"{fmt_hours(total_hours)} שעות"),
        "",
        shift_breakdown(shift, calendar),
        "",
        rtl(f"💰 <b>סה״כ המשמרת: {fmt_money(shift.total_agorot)}</b>"),
    ]

    if status is not None:
        lines += ["", ceiling_block(status)]
    return "\n".join(lines)


# --------------------------------------------------------------- ceiling block

def ceiling_block(status: MonthStatus, with_month: bool = True) -> str:
    """``with_month`` is turned off where the surrounding screen already names
    the month, so it is not repeated two lines apart."""
    prefix = f"📊 {fmt_month(status.year, status.month)}: " if with_month else "💰 "
    lines = [
        rtl(f"{prefix}<b>{fmt_money(status.earned_agorot)}</b> "
            f"מתוך {fmt_money(status.ceiling_agorot)}"),
        rtl(f"{progress_bar(status.pct)} {status.pct:.0f}%"),
    ]
    if status.over_ceiling:
        lines.append(rtl(f"🔴 חריגה של {fmt_money(-status.remaining_agorot)}"))
    elif status.hourly_agorot > 0:
        lines.append(
            rtl(f"נותרו {fmt_money(status.remaining_agorot)} ≈ "
                f"{fmt_hours(status.remaining_base_hours)} שעות רגילות "
                f"({fmt_hours(status.remaining_rest_hours)} שעות שבת)")
        )
    else:
        lines.append(rtl(f"נותרו {fmt_money(status.remaining_agorot)}"))
    return "\n".join(lines)


def status_card(status: MonthStatus) -> str:
    lines = [
        rtl(f"📊 <b>מצב החודש — {fmt_month(status.year, status.month)}</b>"),
        "",
        ceiling_block(status, with_month=False),
        "",
        rtl(f"🕐 סה״כ שעות: <b>{fmt_hours(status.total_hours)}</b> "
            f"ב‑{status.shift_count} משמרות"),
    ]

    if status.tiers:
        lines.append("")
        lines.append(rtl("<b>פילוח לפי תעריף:</b>"))
        for tier in status.tiers:
            label = kind_label(tier.kind)
            lines.append(
                rtl(f"• {fmt_pct(tier.multiplier)} ({label}) · "
                    f"{fmt_hours(tier.hours)} ש׳ · {fmt_money(tier.agorot)}")
            )

    crossing = status.projected_crossing_date()
    if crossing:
        lines += ["", rtl(f"🔮 בקצב הנוכחי תגיע לתקרה בערך ב‑{crossing.strftime('%d.%m')}")]

    return "\n".join(lines)


def forecast_card(status: MonthStatus) -> str:
    lines = [rtl(f"🔮 <b>תחזית — {fmt_month(status.year, status.month)}</b>"), ""]

    if status.hourly_agorot <= 0:
        lines.append(rtl("צריך להגדיר תעריף שעתי כדי לחשב תחזית."))
        return "\n".join(lines)

    if status.over_ceiling:
        lines.append(rtl(f"🔴 כבר עברת את התקרה ב‑{fmt_money(-status.remaining_agorot)}."))
        return "\n".join(lines)

    lines += [
        rtl(f"נותרו <b>{fmt_money(status.remaining_agorot)}</b> עד התקרה, כלומר:"),
        "",
        rtl(f"• {fmt_hours(status.remaining_base_hours)} שעות ביום רגיל (100%)"),
        rtl(f"• {fmt_hours(status.remaining_rest_hours)} שעות בשבת או חג (150%)"),
    ]

    crossing = status.projected_crossing_date()
    if crossing:
        lines += ["", rtl(f"בקצב הנוכחי תגיע לתקרה בערך ב‑{crossing.strftime('%d.%m.%Y')}.")]
    else:
        lines += ["", rtl("בקצב הנוכחי לא תגיע לתקרה עד סוף החודש.")]
    return "\n".join(lines)


# ---------------------------------------------------------------- shift lists

def shift_line(shift: Shift, calendar: CalendarService) -> str:
    start_local = tu.to_local(shift.start_utc)
    end_local = tu.to_local(shift.end_utc)
    hours = sum(s.hours for s in shift.segments)
    kinds = {s.kind for s in shift.segments}
    if kinds & {"shabbat", "chag", "rest"}:
        mark = " 🕯"
    elif kinds & {"night", "early", "dawn"}:
        mark = " 🌙"
    else:
        mark = ""
    return rtl(
        f"{start_local.strftime('%d.%m')} ({day_name(start_local.date())}) · "
        f"{start_local.strftime('%H:%M')}–{end_local.strftime('%H:%M')} · "
        f"{fmt_hours(hours)} ש׳ · {fmt_money(shift.total_agorot)}{mark}"
    )


def shift_button_label(shift: Shift) -> str:
    start_local = tu.to_local(shift.start_utc)
    end_local = tu.to_local(shift.end_utc)
    return (
        f"{start_local.strftime('%d.%m')} · "
        f"{start_local.strftime('%H:%M')}–{end_local.strftime('%H:%M')} · "
        f"{fmt_money(shift.total_agorot)}"
    )


def year_summary(rows: list[tuple[int, int, int, float]], year: int) -> str:
    """rows: (month, earned_agorot, ceiling_agorot, hours)"""
    lines = [rtl(f"🗂 <b>סיכום שנתי — {year}</b>"), ""]
    total = 0
    total_hours = 0.0
    for month, earned, ceiling_agorot, hours in rows:
        total += earned
        total_hours += hours
        flag = " 🔴" if earned > ceiling_agorot else ""
        lines.append(
            rtl(f"• {MONTH_NAMES_HE[month - 1]}: {fmt_money(earned)} · "
                f"{fmt_hours(hours)} ש׳{flag}")
        )
    if not rows:
        lines.append(rtl("אין נתונים לשנה הזו."))
    else:
        lines += ["", rtl(f"<b>סה״כ: {fmt_money(total)} · {fmt_hours(total_hours)} שעות</b>")]
    return "\n".join(lines)
