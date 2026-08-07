"""Calendar classification tests.

The chol hamoed and Yom Haatzmaut cases are the ones that would silently
mis-price real money, so they are asserted explicitly.
"""
import datetime as dt

from salary_bot.core.calendar_service import CalendarService


def test_ordinary_shabbat_is_a_rest_day(cal_tlv):
    assert cal_tlv.is_rest_day(dt.date(2026, 9, 19))          # Saturday
    assert not cal_tlv.is_rest_day(dt.date(2026, 9, 18))      # Friday
    assert cal_tlv.classify_day(dt.date(2026, 9, 19))[1] == "שבת"


def test_chol_hamoed_is_an_ordinary_workday(cal_tlv):
    # Pesach 5786: 2 Apr is yom tov, 3-7 Apr chol hamoed, 8 Apr is yom tov again.
    assert cal_tlv.is_rest_day(dt.date(2026, 4, 2))
    assert cal_tlv.is_rest_day(dt.date(2026, 4, 8))
    for day in (5, 6, 7):
        assert not cal_tlv.is_rest_day(dt.date(2026, 4, day)), f"4/{day} must be a workday"


def test_chol_hamoed_falling_on_shabbat_is_still_a_rest_day(cal_tlv):
    assert cal_tlv.is_rest_day(dt.date(2026, 4, 4))  # Saturday
    assert cal_tlv.classify_day(dt.date(2026, 4, 4))[1] == "שבת"


def test_yom_haatzmaut_is_a_rest_day_despite_not_being_yom_tov(cal_tlv):
    day = dt.date(2026, 4, 22)
    assert cal_tlv.is_rest_day(day)
    assert cal_tlv.classify_day(day)[1] == "יום העצמאות"

    block = cal_tlv.block_containing_day(day)
    assert block is not None
    # No candle lighting exists for it, so the block must still have been built
    # from the sunset/nightfall fallback rather than coming out empty.
    assert block.start < block.end
    assert 20 < (block.end - block.start).total_seconds() / 3600 < 30


def test_consecutive_rest_days_merge_into_one_block(cal_tlv):
    # Rosh Hashana 5787 falls Sat 12 + Sun 13 Sep 2026: one continuous block
    # from Friday candle lighting to Sunday night havdalah.
    block = cal_tlv.block_containing_day(dt.date(2026, 9, 12))
    assert block is not None
    assert block.start.astimezone().date() == dt.date(2026, 9, 11)
    hours = (block.end - block.start).total_seconds() / 3600
    assert 47 < hours < 50, f"expected a ~49h two-day block, got {hours:.1f}h"


def test_block_boundaries_match_candle_lighting_and_havdalah(cal_tlv):
    from zoneinfo import ZoneInfo

    il = ZoneInfo("Asia/Jerusalem")
    block = cal_tlv.block_containing_day(dt.date(2026, 9, 19))
    assert block is not None
    assert block.start.astimezone(il).strftime("%Y-%m-%d %H:%M") == "2026-09-18 18:27"
    assert block.end.astimezone(il).strftime("%Y-%m-%d %H:%M") == "2026-09-19 19:20"


def test_jerusalem_lights_earlier_than_tel_aviv():
    """The 40-minute Jerusalem custom must actually be applied — it moves the
    start of 150% pay, so it is not cosmetic."""
    jlm = CalendarService("jerusalem")
    tlv = CalendarService("tel_aviv")
    j = jlm.block_containing_day(dt.date(2026, 9, 19))
    t = tlv.block_containing_day(dt.date(2026, 9, 19))
    assert j.start < t.start


def test_holiday_label_reports_chol_hamoed_without_pricing_it(cal_tlv):
    assert cal_tlv.holiday_label(dt.date(2026, 4, 6)) == "חול המועד"
    assert not cal_tlv.is_rest_day(dt.date(2026, 4, 6))
