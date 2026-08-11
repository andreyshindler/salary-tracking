"""Golden cases for the pricing engine.

Two rates only: 150% for night, Shabbat and חג; 100% for everything else.
Shift length never affects the rate.
"""
import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from salary_bot.core.pay_engine import price_shift
from tests.conftest import RATE, local

IL = ZoneInfo("Asia/Jerusalem")


def _hours_at(priced, multiplier):
    return round(sum(s.hours for s in priced.segments if s.multiplier == multiplier), 4)


def _kinds(priced):
    return [s.kind for s in priced.segments]


def test_segments_are_contiguous_and_total_correctly(cal_tlv):
    priced = price_shift(local(2026, 6, 9, 18), local(2026, 6, 10, 4), RATE, cal_tlv)
    assert priced.segments[0].start == priced.start
    assert priced.segments[-1].end == priced.end
    for a, b in zip(priced.segments, priced.segments[1:]):
        assert a.end == b.start
    assert round(sum(s.hours for s in priced.segments), 6) == priced.total_hours


# --------------------------------------------------------------- ordinary time

def test_daytime_weekday_shift_is_all_base_rate(cal_tlv):
    priced = price_shift(local(2026, 6, 9, 9), local(2026, 6, 9, 15), RATE, cal_tlv)
    assert priced.total_hours == 6.0
    assert len(priced.segments) == 1
    assert priced.segments[0].multiplier == 1.0
    assert priced.total_agorot == 6 * RATE


def test_length_of_shift_never_creates_a_premium(cal_tlv):
    """A twelve-hour day shift is 100% throughout — there is no overtime by
    hours worked, only by clock and calendar."""
    priced = price_shift(local(2026, 6, 9, 8), local(2026, 6, 9, 20), RATE, cal_tlv)
    assert priced.total_hours == 12.0
    assert len(priced.segments) == 1
    assert _hours_at(priced, 1.0) == 12.0
    assert priced.total_agorot == 12 * RATE


# ---------------------------------------------------------------------- night

def test_evening_shift_switches_to_150_at_22(cal_tlv):
    priced = price_shift(local(2026, 6, 9, 20), local(2026, 6, 10, 0), RATE, cal_tlv)
    assert len(priced.segments) == 2

    before, after = priced.segments
    assert before.multiplier == 1.0 and before.hours == 2.0
    assert after.multiplier == 1.5 and after.hours == 2.0
    assert after.kind == "night"
    assert after.start.astimezone(IL).strftime("%H:%M") == "22:00"
    assert priced.total_agorot == round(2 * RATE + 2 * 1.5 * RATE)


def test_morning_shift_drops_to_100_at_08(cal_tlv):
    priced = price_shift(local(2026, 6, 9, 6), local(2026, 6, 9, 10), RATE, cal_tlv)
    assert len(priced.segments) == 2

    night, day = priced.segments
    assert night.multiplier == 1.5 and night.hours == 2.0
    assert night.kind == "night"
    assert day.multiplier == 1.0 and day.hours == 2.0
    assert night.end.astimezone(IL).strftime("%H:%M") == "08:00"


def test_a_whole_night_shift_is_entirely_150(cal_tlv):
    """22:00-04:00 sits inside the night window from end to end."""
    priced = price_shift(local(2026, 6, 9, 22), local(2026, 6, 10, 4), RATE, cal_tlv)
    assert priced.total_hours == 6.0
    assert len(priced.segments) == 1, "midnight is not a rate change"
    assert priced.segments[0].kind == "night"
    assert priced.total_agorot == round(6 * 1.5 * RATE)


def test_shift_spanning_evening_night_and_morning(cal_tlv):
    priced = price_shift(local(2026, 6, 9, 20), local(2026, 6, 10, 10), RATE, cal_tlv)
    assert priced.total_hours == 14.0
    assert _kinds(priced) == ["regular", "night", "regular"]
    assert _hours_at(priced, 1.0) == 4.0    # 20:00-22:00 and 08:00-10:00
    assert _hours_at(priced, 1.5) == 10.0   # 22:00-08:00


# ------------------------------------------------------------- Shabbat and chag

def test_friday_evening_shift_switches_to_150_at_candle_lighting(cal_tlv):
    """Fri 18 Sep 2026, Tel Aviv candle lighting 18:27."""
    priced = price_shift(local(2026, 9, 18, 16), local(2026, 9, 18, 21, 30), RATE, cal_tlv)
    assert len(priced.segments) == 2

    before, after = priced.segments
    assert before.multiplier == 1.0 and before.kind == "regular"
    assert after.multiplier == 1.5 and after.kind == "rest"
    assert after.reason == "שבת"
    assert after.start.astimezone(IL).strftime("%H:%M") == "18:27"
    assert before.hours == pytest.approx(2.45, abs=0.01)
    assert after.hours == pytest.approx(3.05, abs=0.01)


def test_premiums_do_not_stack_and_night_inside_shabbat_is_one_segment(cal_tlv):
    """20:00-23:00 on Friday is entirely within Shabbat and crosses 22:00.
    Both stretches are 150%, so it must stay a single row rather than being
    split into two identical-looking ones."""
    priced = price_shift(local(2026, 9, 18, 20), local(2026, 9, 18, 23), RATE, cal_tlv)
    assert len(priced.segments) == 1
    assert priced.segments[0].kind == "rest"
    assert priced.segments[0].multiplier == 1.5, "night + Shabbat must not reach 200%"
    assert priced.total_agorot == round(3 * 1.5 * RATE)


def test_saturday_night_shift_drops_at_havdalah_then_rises_again_at_22(cal_tlv):
    """Sat 19 Sep 2026, havdalah 19:20. Three rates in one shift."""
    priced = price_shift(local(2026, 9, 19, 18), local(2026, 9, 19, 23), RATE, cal_tlv)
    assert _kinds(priced) == ["rest", "regular", "night"]

    shabbat, evening, night = priced.segments
    assert shabbat.multiplier == 1.5
    assert shabbat.end.astimezone(IL).strftime("%H:%M") == "19:20"
    assert evening.multiplier == 1.0
    assert night.multiplier == 1.5
    assert night.start.astimezone(IL).strftime("%H:%M") == "22:00"
    assert evening.hours == pytest.approx(2.667, abs=0.01)
    assert night.hours == 1.0


def test_a_long_shabbat_shift_stays_at_150_throughout(cal_tlv):
    priced = price_shift(local(2026, 9, 19, 6), local(2026, 9, 19, 18), RATE, cal_tlv)
    assert priced.total_hours == 12.0
    assert len(priced.segments) == 1, "length must not create a higher tier"
    assert priced.segments[0].multiplier == 1.5
    assert priced.total_agorot == round(12 * 1.5 * RATE)


def test_yom_kippur_is_paid_at_the_premium_rate(cal_tlv):
    # Yom Kippur 5787 = Mon 21 Sep 2026.
    priced = price_shift(local(2026, 9, 21, 10), local(2026, 9, 21, 14), RATE, cal_tlv)
    assert all(s.kind == "rest" for s in priced.segments)
    assert priced.total_agorot == round(4 * 1.5 * RATE)


def test_chol_hamoed_daytime_is_paid_at_the_ordinary_rate(cal_tlv):
    """The expensive mistake: chol hamoed priced as a holiday would be +50%."""
    priced = price_shift(local(2026, 4, 6, 9), local(2026, 4, 6, 15), RATE, cal_tlv)
    assert all(s.kind == "regular" for s in priced.segments)
    assert priced.total_agorot == 6 * RATE


# ----------------------------------------------------------------- edge cases

def test_dst_change_is_measured_in_real_hours(cal_tlv):
    """Israel ends DST on the last Sunday of October; 00:00-05:00 local on that
    night is six real hours, and the engine must bill six."""
    end_of_dst = dt.date(2026, 10, 25)
    assert end_of_dst.weekday() == 6, "guard: expected a Sunday"

    start = dt.datetime(2026, 10, 25, 0, 0, tzinfo=IL)
    end = dt.datetime(2026, 10, 25, 5, 0, tzinfo=IL)
    real_hours = (end.astimezone(dt.timezone.utc) - start.astimezone(dt.timezone.utc)).total_seconds() / 3600
    assert real_hours == 6.0, "guard: the tz database should show the fall-back here"

    priced = price_shift(start, end, RATE, cal_tlv)
    assert priced.total_hours == 6.0
    # The whole span is inside the night window, before and after the change.
    assert all(s.kind == "night" for s in priced.segments)


def test_premiums_can_be_disabled(cal_tlv):
    """A flat-rate arrangement: everything at 100%, Shabbat included."""
    priced = price_shift(
        local(2026, 9, 19, 20), local(2026, 9, 20, 2), RATE, cal_tlv, apply_premiums=False
    )
    assert priced.total_hours == 6.0
    assert len(priced.segments) == 1
    assert _hours_at(priced, 1.0) == 6.0
    assert priced.total_agorot == 6 * RATE


def test_a_custom_night_window_is_respected(cal_tlv):
    priced = price_shift(
        local(2026, 6, 9, 22), local(2026, 6, 10, 2), RATE, cal_tlv,
        night_start_min=23 * 60, night_end_min=6 * 60,
    )
    assert _kinds(priced) == ["regular", "night"]
    assert priced.segments[0].hours == 1.0   # 22:00-23:00 is now ordinary
    assert priced.segments[1].hours == 3.0   # 23:00-02:00


def test_an_empty_night_window_disables_the_night_premium(cal_tlv):
    priced = price_shift(
        local(2026, 6, 9, 22), local(2026, 6, 10, 4), RATE, cal_tlv,
        night_start_min=0, night_end_min=0,
    )
    assert all(s.kind == "regular" for s in priced.segments)
    assert priced.total_agorot == 6 * RATE


def test_rejects_inverted_or_empty_shifts(cal_tlv):
    with pytest.raises(ValueError):
        price_shift(local(2026, 6, 9, 12), local(2026, 6, 9, 12), RATE, cal_tlv)
    with pytest.raises(ValueError):
        price_shift(local(2026, 6, 9, 14), local(2026, 6, 9, 12), RATE, cal_tlv)


def test_rejects_naive_datetimes(cal_tlv):
    with pytest.raises(ValueError):
        price_shift(
            dt.datetime(2026, 6, 9, 8), dt.datetime(2026, 6, 9, 12), RATE, cal_tlv
        )
