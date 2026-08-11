"""Golden cases for the pricing engine.

Both the multiplier and the base rate change with the clock, so the tests use
two widely separated rates — any amount identifies which was applied.

    day   = 100 NIS/hour
    night = 200 NIS/hour
"""
import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from salary_bot.core.pay_engine import price_shift
from tests.conftest import NIGHT_RATE, RATE, local

IL = ZoneInfo("Asia/Jerusalem")


def _priced(cal, start, end, **kw):
    return price_shift(start, end, RATE, NIGHT_RATE, cal, **kw)


def _rows(priced):
    """(kind, hours, multiplier, rate) per segment — the whole shape at a glance."""
    return [(s.kind, round(s.hours, 4), s.multiplier, s.rate_agorot) for s in priced.segments]


def test_segments_are_contiguous_and_total_correctly(cal_tlv):
    priced = _priced(cal_tlv, local(2026, 6, 10, 18), local(2026, 6, 11, 10))
    assert priced.segments[0].start == priced.start
    assert priced.segments[-1].end == priced.end
    for a, b in zip(priced.segments, priced.segments[1:]):
        assert a.end == b.start
    assert round(sum(s.hours for s in priced.segments), 6) == priced.total_hours
    assert priced.total_agorot == sum(s.amount_agorot for s in priced.segments)


# ------------------------------------------------------------------ the bands

def test_a_full_weekday_covers_all_four_bands(cal_tlv):
    """08:00 Wednesday to 08:00 Thursday exercises the whole table."""
    priced = _priced(cal_tlv, local(2026, 6, 10, 8), local(2026, 6, 11, 8))
    assert priced.total_hours == 24.0
    assert _rows(priced) == [
        ("day",   14.0, 1.0,  RATE),        # 08:00-22:00
        ("night",  7.0, 1.0,  NIGHT_RATE),  # 22:00-05:00
        ("early",  2.0, 1.25, NIGHT_RATE),  # 05:00-07:00
        ("dawn",   1.0, 2.0,  NIGHT_RATE),  # 07:00-08:00
    ]
    expected = round(14 * RATE + 7 * NIGHT_RATE + 2 * 1.25 * NIGHT_RATE + 1 * 2.0 * NIGHT_RATE)
    assert priced.total_agorot == expected


def test_daytime_shift_is_the_day_band_only(cal_tlv):
    priced = _priced(cal_tlv, local(2026, 6, 10, 9), local(2026, 6, 10, 15))
    assert _rows(priced) == [("day", 6.0, 1.0, RATE)]
    assert priced.total_agorot == 6 * RATE


def test_length_of_shift_never_creates_a_premium(cal_tlv):
    """A twelve-hour day shift stays inside the 08:00-22:00 band throughout."""
    priced = _priced(cal_tlv, local(2026, 6, 10, 8), local(2026, 6, 10, 20))
    assert _rows(priced) == [("day", 12.0, 1.0, RATE)]
    assert priced.total_agorot == 12 * RATE


def test_the_night_band_pays_the_night_rate_at_100_percent(cal_tlv):
    """22:00-05:00 is still 100%, but on the higher base rate."""
    priced = _priced(cal_tlv, local(2026, 6, 10, 22), local(2026, 6, 11, 5))
    assert _rows(priced) == [("night", 7.0, 1.0, NIGHT_RATE)]
    assert priced.total_agorot == 7 * NIGHT_RATE


def test_the_early_and_dawn_bands_carry_their_multipliers(cal_tlv):
    priced = _priced(cal_tlv, local(2026, 6, 10, 5), local(2026, 6, 10, 8))
    assert _rows(priced) == [
        ("early", 2.0, 1.25, NIGHT_RATE),
        ("dawn",  1.0, 2.0,  NIGHT_RATE),
    ]
    assert priced.total_agorot == round(2 * 1.25 * NIGHT_RATE + 1 * 2.0 * NIGHT_RATE)


def test_midnight_is_not_a_rate_change(cal_tlv):
    priced = _priced(cal_tlv, local(2026, 6, 10, 23), local(2026, 6, 11, 1))
    assert len(priced.segments) == 1
    assert priced.segments[0].kind == "night"


# ------------------------------------------------------------- Shabbat window

def test_the_shabbat_window_runs_friday_2000_to_saturday_2000(cal_tlv):
    priced = _priced(cal_tlv, local(2026, 9, 18, 20), local(2026, 9, 19, 20))
    assert _rows(priced) == [("shabbat", 24.0, 1.5, RATE)]
    assert priced.total_agorot == round(24 * 1.5 * RATE)


def test_shabbat_overrides_the_daily_bands(cal_tlv):
    """Saturday 05:00-07:00 would be 125% x night on an ordinary day; inside the
    Shabbat window it is 150% x day instead."""
    priced = _priced(cal_tlv, local(2026, 9, 19, 5), local(2026, 9, 19, 7))
    assert _rows(priced) == [("shabbat", 2.0, 1.5, RATE)]


def test_entering_and_leaving_the_shabbat_window(cal_tlv):
    priced = _priced(cal_tlv, local(2026, 9, 18, 18), local(2026, 9, 19, 23))
    assert _rows(priced) == [
        ("day",     2.0, 1.0, RATE),        # Fri 18:00-20:00
        ("shabbat", 24.0, 1.5, RATE),       # Fri 20:00 -> Sat 20:00
        ("day",     2.0, 1.0, RATE),        # Sat 20:00-22:00
        ("night",   1.0, 1.0, NIGHT_RATE),  # Sat 22:00-23:00
    ]


def test_friday_daytime_is_ordinary(cal_tlv):
    """The window opens at 20:00, so Friday morning is a normal working day."""
    priced = _priced(cal_tlv, local(2026, 9, 18, 9), local(2026, 9, 18, 15))
    assert _rows(priced) == [("day", 6.0, 1.0, RATE)]


# ---------------------------------------------------------------- chag window

def test_chag_is_paid_at_200_percent(cal_tlv):
    """Yom Kippur 5787 is Mon 21 Sep 2026, so the window is Sun 20:00 -> Mon 20:00."""
    priced = _priced(cal_tlv, local(2026, 9, 21, 10), local(2026, 9, 21, 14))
    assert _rows(priced) == [("chag", 4.0, 2.0, RATE)]
    assert priced.total_agorot == round(4 * 2.0 * RATE)


def test_the_chag_window_opens_the_evening_before(cal_tlv):
    priced = _priced(cal_tlv, local(2026, 9, 20, 18), local(2026, 9, 20, 22))
    assert _rows(priced) == [
        ("day",  2.0, 1.0, RATE),   # 18:00-20:00, still ordinary
        ("chag", 2.0, 2.0, RATE),   # 20:00 onward
    ]


def test_chag_beats_shabbat_where_they_overlap(cal_tlv):
    """Rosh Hashana 5787 falls on Sat 12 Sep 2026. The day is both, and the
    better-paying rule applies."""
    priced = _priced(cal_tlv, local(2026, 9, 12, 10), local(2026, 9, 12, 14))
    assert _rows(priced) == [("chag", 4.0, 2.0, RATE)]


def test_chol_hamoed_is_an_ordinary_working_day(cal_tlv):
    """The expensive mistake: chol hamoed priced as chag would double the pay."""
    priced = _priced(cal_tlv, local(2026, 4, 6, 9), local(2026, 4, 6, 15))
    assert _rows(priced) == [("day", 6.0, 1.0, RATE)]
    assert priced.total_agorot == 6 * RATE


def test_yom_haatzmaut_counts_as_chag(cal_tlv):
    priced = _priced(cal_tlv, local(2026, 4, 22, 10), local(2026, 4, 22, 14))
    assert _rows(priced) == [("chag", 4.0, 2.0, RATE)]


# ----------------------------------------------------------------- edge cases

def test_dst_change_is_measured_in_real_hours(cal_tlv):
    """Israel ends DST on the last Sunday of October; 00:00-05:00 local that
    night is six real hours, and the engine must bill six."""
    end_of_dst = dt.date(2026, 10, 25)
    assert end_of_dst.weekday() == 6, "guard: expected a Sunday"

    start = dt.datetime(2026, 10, 25, 0, 0, tzinfo=IL)
    end = dt.datetime(2026, 10, 25, 5, 0, tzinfo=IL)
    real_hours = (end.astimezone(dt.timezone.utc) - start.astimezone(dt.timezone.utc)).total_seconds() / 3600
    assert real_hours == 6.0, "guard: the tz database should show the fall-back here"

    priced = _priced(cal_tlv, start, end)
    assert priced.total_hours == 6.0
    # Still one band: 00:00-05:00 is night on both sides of the change.
    assert _rows(priced) == [("night", 6.0, 1.0, NIGHT_RATE)]


def test_premiums_can_be_disabled(cal_tlv):
    """A flat-rate arrangement: everything at the day rate, Shabbat included."""
    priced = _priced(cal_tlv, local(2026, 9, 18, 20), local(2026, 9, 19, 2),
                     apply_premiums=False)
    assert _rows(priced) == [("day", 6.0, 1.0, RATE)]
    assert priced.total_agorot == 6 * RATE


def test_a_single_rate_arrangement_still_works(cal_tlv):
    """Passing the same figure for both leaves only the multipliers varying."""
    priced = price_shift(local(2026, 6, 10, 22), local(2026, 6, 11, 8), RATE, RATE, cal_tlv)
    assert {s.rate_agorot for s in priced.segments} == {RATE}
    assert priced.total_agorot == round((7 + 2 * 1.25 + 1 * 2.0) * RATE)


def test_rejects_inverted_or_empty_shifts(cal_tlv):
    with pytest.raises(ValueError):
        _priced(cal_tlv, local(2026, 6, 10, 12), local(2026, 6, 10, 12))
    with pytest.raises(ValueError):
        _priced(cal_tlv, local(2026, 6, 10, 14), local(2026, 6, 10, 12))


def test_rejects_naive_datetimes(cal_tlv):
    with pytest.raises(ValueError):
        _priced(cal_tlv, dt.datetime(2026, 6, 10, 8), dt.datetime(2026, 6, 10, 12))
