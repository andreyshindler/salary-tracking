"""Golden cases for the pricing engine."""
import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from salary_bot.core.pay_engine import price_shift
from tests.conftest import RATE, local

IL = ZoneInfo("Asia/Jerusalem")


def _hours_at(priced, multiplier):
    return round(sum(s.hours for s in priced.segments if s.multiplier == multiplier), 4)


def test_segments_are_contiguous_and_total_correctly(cal_tlv):
    priced = price_shift(local(2026, 6, 9, 8), local(2026, 6, 9, 20), RATE, cal_tlv)
    assert priced.segments[0].start == priced.start
    assert priced.segments[-1].end == priced.end
    for a, b in zip(priced.segments, priced.segments[1:]):
        assert a.end == b.start
    assert round(sum(s.hours for s in priced.segments), 6) == priced.total_hours


def test_plain_weekday_shift_under_threshold_is_all_base_rate(cal_tlv):
    priced = price_shift(local(2026, 6, 9, 9), local(2026, 6, 9, 15), RATE, cal_tlv)
    assert priced.total_hours == 6.0
    assert len(priced.segments) == 1
    assert priced.segments[0].multiplier == 1.0
    assert priced.total_agorot == 6 * RATE


def test_twelve_hour_weekday_shift_splits_into_overtime_tiers(cal_tlv):
    priced = price_shift(local(2026, 6, 9, 8), local(2026, 6, 9, 20), RATE, cal_tlv)
    assert priced.total_hours == 12.0
    assert _hours_at(priced, 1.0) == 8.0
    assert _hours_at(priced, 1.25) == 2.0
    assert _hours_at(priced, 1.5) == 2.0
    # 8*100 + 2*125 + 2*150 = 1350 NIS
    assert priced.total_agorot == 135_000


def test_friday_evening_shift_switches_to_150_at_candle_lighting(cal_tlv):
    """Fri 18 Sep 2026, Tel Aviv candle lighting 18:27."""
    priced = price_shift(local(2026, 9, 18, 16), local(2026, 9, 18, 21, 30), RATE, cal_tlv)
    assert len(priced.segments) == 2

    before, after = priced.segments
    assert before.multiplier == 1.0
    assert before.kind == "regular"
    assert after.multiplier == 1.5
    assert after.kind == "rest"
    assert after.reason == "שבת"
    assert after.start.astimezone(IL).strftime("%H:%M") == "18:27"

    assert before.hours == pytest.approx(2.45, abs=0.01)   # 16:00 -> 18:27
    assert after.hours == pytest.approx(3.05, abs=0.01)    # 18:27 -> 21:30


def test_saturday_night_shift_drops_to_100_at_havdalah(cal_tlv):
    """Sat 19 Sep 2026, havdalah 19:20."""
    priced = price_shift(local(2026, 9, 19, 18), local(2026, 9, 19, 23), RATE, cal_tlv)
    assert len(priced.segments) == 2

    during, after = priced.segments
    assert during.multiplier == 1.5
    assert after.multiplier == 1.0
    assert during.end.astimezone(IL).strftime("%H:%M") == "19:20"
    assert during.hours == pytest.approx(1.333, abs=0.01)
    assert after.hours == pytest.approx(3.667, abs=0.01)


def test_yom_kippur_is_paid_at_rest_rate(cal_tlv):
    # Yom Kippur 5787 = Mon 21 Sep 2026.
    priced = price_shift(local(2026, 9, 21, 10), local(2026, 9, 21, 14), RATE, cal_tlv)
    assert all(s.kind == "rest" for s in priced.segments)
    assert priced.total_agorot == round(4 * 1.5 * RATE)


def test_chol_hamoed_is_paid_at_ordinary_rate(cal_tlv):
    """The expensive mistake: chol hamoed priced as a holiday would be +50%."""
    priced = price_shift(local(2026, 4, 6, 9), local(2026, 4, 6, 15), RATE, cal_tlv)
    assert all(s.kind == "regular" for s in priced.segments)
    assert priced.total_agorot == 6 * RATE


def test_shift_crossing_midnight_is_one_working_day_for_overtime(cal_tlv):
    """22:00 Tue -> 04:00 Wed is 6 hours, all still under the daily threshold;
    midnight must not reset the overtime counter or split the segment."""
    priced = price_shift(local(2026, 6, 9, 22), local(2026, 6, 10, 4), RATE, cal_tlv)
    assert priced.total_hours == 6.0
    assert len(priced.segments) == 1
    assert priced.total_agorot == 6 * RATE


def test_overtime_carries_across_midnight(cal_tlv):
    priced = price_shift(local(2026, 6, 9, 18), local(2026, 6, 10, 8), RATE, cal_tlv)
    assert priced.total_hours == 14.0
    assert _hours_at(priced, 1.0) == 8.0
    assert _hours_at(priced, 1.25) == 2.0
    assert _hours_at(priced, 1.5) == 4.0


def test_rest_day_overtime_uses_the_175_and_200_tiers(cal_tlv):
    """A long Shabbat shift: 150% base, then 175%, then 200%."""
    priced = price_shift(local(2026, 9, 19, 6), local(2026, 9, 19, 18), RATE, cal_tlv)
    assert priced.total_hours == 12.0
    assert all(s.kind == "rest" for s in priced.segments)  # all before havdalah
    assert _hours_at(priced, 1.5) == 8.0
    assert _hours_at(priced, 1.75) == 2.0
    assert _hours_at(priced, 2.0) == 2.0


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


def test_overtime_can_be_disabled(cal_tlv):
    priced = price_shift(
        local(2026, 6, 9, 8), local(2026, 6, 9, 20), RATE, cal_tlv, apply_overtime=False
    )
    assert priced.total_hours == 12.0
    assert _hours_at(priced, 1.0) == 12.0
    assert priced.total_agorot == 12 * RATE


def test_custom_daily_threshold_is_respected(cal_tlv):
    priced = price_shift(
        local(2026, 6, 9, 8), local(2026, 6, 9, 19), RATE, cal_tlv, daily_ot_threshold=8.6
    )
    assert _hours_at(priced, 1.0) == 8.6
    assert _hours_at(priced, 1.25) == 2.0
    assert _hours_at(priced, 1.5) == pytest.approx(0.4, abs=0.001)


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
