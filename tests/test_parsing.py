import datetime as dt

import pytest

from salary_bot.core.parsing import (
    ParseError, parse_amount, parse_hours, parse_manual_entry, parse_time_of_day,
)

TODAY = dt.date(2026, 9, 18)


def test_parse_amount_variants():
    assert parse_amount("85") == 8500
    assert parse_amount("85.5") == 8550
    assert parse_amount("  ₪85  ") == 8500
    assert parse_amount("85 שח") == 8500
    assert parse_amount("10,113") == 1_011_300   # thousands separator
    assert parse_amount("85,5") == 8550          # comma as decimal point


def test_parse_amount_rejects_nonsense():
    for bad in ["abc", "", "8.5.5", "-5"]:
        with pytest.raises(ParseError):
            parse_amount(bad)


def test_parse_hours():
    assert parse_hours("8") == 8.0
    assert parse_hours("8.6") == 8.6
    assert parse_hours("8,6") == 8.6
    for bad in ["0", "25", "x"]:
        with pytest.raises(ParseError):
            parse_hours(bad)


def test_parse_time_of_day():
    assert parse_time_of_day("16:00", TODAY) == dt.datetime(2026, 9, 18, 16, 0)
    assert parse_time_of_day("  9:05 ", TODAY) == dt.datetime(2026, 9, 18, 9, 5)
    with pytest.raises(ParseError):
        parse_time_of_day("25:00", TODAY)


def test_manual_entry_two_times_defaults_to_today():
    start, end = parse_manual_entry("16:00 21:30", TODAY)
    assert start == dt.datetime(2026, 9, 18, 16, 0)
    assert end == dt.datetime(2026, 9, 18, 21, 30)


def test_manual_entry_accepts_a_dash_separator():
    assert parse_manual_entry("16:00-21:30", TODAY) == parse_manual_entry("16:00 21:30", TODAY)
    assert parse_manual_entry("16:00–21:30", TODAY) == parse_manual_entry("16:00 21:30", TODAY)


def test_manual_entry_relative_days():
    start, _ = parse_manual_entry("אתמול 16:00 21:30", TODAY)
    assert start.date() == dt.date(2026, 9, 17)

    start, _ = parse_manual_entry("שלשום 16:00 21:30", TODAY)
    assert start.date() == dt.date(2026, 9, 16)

    start, _ = parse_manual_entry("היום 16:00 21:30", TODAY)
    assert start.date() == TODAY


def test_manual_entry_explicit_dates():
    start, end = parse_manual_entry("12/09 16:00 21:30", TODAY)
    assert start == dt.datetime(2026, 9, 12, 16, 0)

    start, _ = parse_manual_entry("12.09.2025 08:00 12:00", TODAY)
    assert start.date() == dt.date(2025, 9, 12)

    start, _ = parse_manual_entry("1/3/26 08:00 12:00", TODAY)
    assert start.date() == dt.date(2026, 3, 1)


def test_manual_entry_overnight_shift_rolls_to_next_day():
    start, end = parse_manual_entry("22:00 04:00", TODAY)
    assert start == dt.datetime(2026, 9, 18, 22, 0)
    assert end == dt.datetime(2026, 9, 19, 4, 0)
    assert (end - start) == dt.timedelta(hours=6)


def test_manual_entry_rejects_bad_input():
    with pytest.raises(ParseError):
        parse_manual_entry("16:00", TODAY)          # only one time
    with pytest.raises(ParseError):
        parse_manual_entry("", TODAY)
    with pytest.raises(ParseError):
        parse_manual_entry("8:00 12:00 16:00", TODAY)  # three times
    with pytest.raises(ParseError):
        parse_manual_entry("31/02 08:00 12:00", TODAY)  # impossible date
