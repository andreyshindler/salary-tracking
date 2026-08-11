"""Israeli calendar: which stretches of time are paid at rest-day rates.

The unit this module produces is a **rest block** — a continuous interval from
candle lighting to havdalah during which work is paid at the rest-day premium.
Blocks, not days, because a rest period does not align with calendar dates: it
starts on Friday evening and ends on Saturday night, and consecutive rest days
(Rosh Hashana falling on Shabbat, say) merge into one 49-hour block.

Two classification points that are easy to get wrong and are covered by tests:

* **Chol hamoed is an ordinary workday.** Only the nine statutory yom tov days
  carry rest-day pay. Treating chol hamoed as a holiday would silently inflate
  earnings by 50% for a week twice a year.
* **Yom Haatzmaut is not halachic yom tov**, so ``is_yom_tov`` is False for it,
  but it *is* a paid rest day under Israeli labour law. It is added explicitly,
  and because it has no candle lighting, its block falls back to sunset/nightfall.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from hdate import HDateInfo, Location, Zmanim

from .cities import get_city

# Rest days for pay purposes that hdate does not flag as yom tov.
LABOR_REST_HOLIDAYS = {"yom_haatzmaut"}

HOLIDAY_HE = {
    "rosh_hashana": "ראש השנה",
    "yom_kippur": "יום כיפור",
    "sukkot": "סוכות",
    "shmini_atzeret": "שמיני עצרת",
    "simchat_torah": "שמחת תורה",
    "pesach": "פסח",
    "pesach_vii": "שביעי של פסח",
    "shavuot": "שבועות",
    "yom_haatzmaut": "יום העצמאות",
}

SHABBAT_HE = "שבת"


@dataclass(frozen=True)
class RestBlock:
    """A continuous rest period, in aware UTC."""

    start: dt.datetime
    end: dt.datetime
    label: str

    def contains(self, moment: dt.datetime) -> bool:
        return self.start <= moment < self.end


def _as_utc(value) -> dt.datetime | None:
    """Normalise hdate's two return shapes (``Zman`` wrapper or plain datetime)
    into an aware UTC datetime."""
    if value is None:
        return None
    if hasattr(value, "utc"):
        value = value.utc
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


class CalendarService:
    def __init__(self, city_key: str = "tel_aviv") -> None:
        city = get_city(city_key)
        self.city = city
        self._location = Location(
            name=city.name_he,
            latitude=city.latitude,
            longitude=city.longitude,
            timezone="Asia/Jerusalem",
            diaspora=False,
        )
        self._day_cache: dict[dt.date, tuple[bool, str]] = {}
        self._block_cache: dict[dt.date, RestBlock | None] = {}

    # ---------------------------------------------------------------- days

    def classify_day(self, day: dt.date) -> tuple[bool, str]:
        """(is_rest_day, hebrew_label) for a calendar date."""
        cached = self._day_cache.get(day)
        if cached is not None:
            return cached

        info = HDateInfo(date=day, diaspora=False)
        names = [h.name for h in info.holidays]

        if info.is_yom_tov:
            label = next((HOLIDAY_HE[n] for n in names if n in HOLIDAY_HE), "חג")
            if info.is_shabbat:
                label = f"{SHABBAT_HE} ו{label}"
            result = (True, label)
        elif set(names) & LABOR_REST_HOLIDAYS:
            result = (True, HOLIDAY_HE["yom_haatzmaut"])
        elif info.is_shabbat:
            result = (True, SHABBAT_HE)
        else:
            result = (False, "")

        self._day_cache[day] = result
        return result

    def is_rest_day(self, day: dt.date) -> bool:
        return self.classify_day(day)[0]

    def rest_kind(self, day: dt.date) -> str | None:
        """``"chag"``, ``"shabbat"`` or None — the two are paid differently.

        Chag wins when a holiday falls on Shabbat, since it carries the higher
        rate. Chol hamoed on a Saturday is Shabbat, not chag.
        """
        info = HDateInfo(date=day, diaspora=False)
        names = {h.name for h in info.holidays}
        if info.is_yom_tov or (names & LABOR_REST_HOLIDAYS):
            return "chag"
        if info.is_shabbat:
            return "shabbat"
        return None

    def holiday_label(self, day: dt.date) -> str:
        """Hebrew holiday name for a date, including non-rest ones like chol
        hamoed — used to annotate the shift list, not to price anything."""
        rest, label = self.classify_day(day)
        if rest:
            return label
        names = [h.name for h in HDateInfo(date=day, diaspora=False).holidays]
        for n in names:
            if n.startswith("hol_hamoed"):
                return "חול המועד"
        return ""

    # -------------------------------------------------------------- blocks

    def _zmanim(self, day: dt.date) -> Zmanim:
        return Zmanim(
            date=day,
            location=self._location,
            candle_lighting_offset=self.city.candle_offset_minutes,
        )

    def block_containing_day(self, day: dt.date) -> RestBlock | None:
        """The rest block this date belongs to, or None if it is a workday."""
        if day in self._block_cache:
            return self._block_cache[day]

        if not self.is_rest_day(day):
            self._block_cache[day] = None
            return None

        one_day = dt.timedelta(days=1)
        first = day
        while self.is_rest_day(first - one_day):
            first -= one_day
        last = day
        while self.is_rest_day(last + one_day):
            last += one_day

        erev = first - one_day
        z_erev = self._zmanim(erev)
        # Yom Haatzmaut has no candle lighting; its rest period still begins the
        # previous evening, so fall back to sunset.
        start = _as_utc(z_erev.candle_lighting) or _as_utc(z_erev.shkia)

        z_last = self._zmanim(last)
        # havdalah is None when the next day is also yom tov; that case never
        # reaches here because such days are merged into one block above. It is
        # also None for Yom Haatzmaut, hence the nightfall fallback.
        end = _as_utc(z_last.havdalah) or _as_utc(z_last.tset_hakohavim_shabbat)

        labels: list[str] = []
        cursor = first
        while cursor <= last:
            lbl = self.classify_day(cursor)[1]
            if lbl and lbl not in labels:
                labels.append(lbl)
            cursor += one_day

        block = RestBlock(start=start, end=end, label=" / ".join(labels))
        for d in _date_range(first, last):
            self._block_cache[d] = block
        return block

    def rest_blocks_overlapping(
        self, start: dt.datetime, end: dt.datetime
    ) -> list[RestBlock]:
        """Every rest block intersecting [start, end), in aware UTC.

        Scans a two-day margin either side so a block that begins before the
        shift (Friday candle lighting for a shift starting Saturday morning) is
        still found.
        """
        margin = dt.timedelta(days=2)
        cursor = (start - margin).date()
        final = (end + margin).date()

        blocks: list[RestBlock] = []
        while cursor <= final:
            block = self.block_containing_day(cursor)
            if block is not None and block not in blocks:
                if block.start < end and block.end > start:
                    blocks.append(block)
            cursor += dt.timedelta(days=1)
        return sorted(blocks, key=lambda b: b.start)

    def is_rest_at(self, moment: dt.datetime) -> tuple[bool, str]:
        """(is_rest, label) for an exact instant."""
        for block in self.rest_blocks_overlapping(moment, moment + dt.timedelta(seconds=1)):
            if block.contains(moment):
                return True, block.label
        return False, ""


def _date_range(first: dt.date, last: dt.date):
    cursor = first
    while cursor <= last:
        yield cursor
        cursor += dt.timedelta(days=1)
