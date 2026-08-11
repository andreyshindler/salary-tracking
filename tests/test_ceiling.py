"""Ceiling aggregation and the versioned rate/ceiling lookups."""
import datetime as dt

import pytest

from salary_bot.config import DEFAULT_CEILING_AGOROT
from salary_bot.core import ceiling as ceiling_mod
from salary_bot.core import db, repo
from salary_bot.core import timeutil as tu
from tests.conftest import NIGHT_RATE, RATE, local, workdays


def _add(session, user, cal, start, end):
    return repo.add_manual_shift(
        session, user, tu.to_utc_naive(start), tu.to_utc_naive(end), cal
    )


def test_new_user_is_seeded_with_the_10113_ceiling(session):
    u = db.get_or_create_user(session, tg_user_id=99)
    assert repo.effective_ceiling(session, u.id, dt.date(2026, 6, 1)) == DEFAULT_CEILING_AGOROT
    assert DEFAULT_CEILING_AGOROT == 1_011_300


def test_manual_shift_is_priced_and_segments_stored(session, user, cal):
    shift = _add(session, user, cal, local(2026, 6, 9, 9), local(2026, 6, 9, 15))
    assert shift.total_agorot == 6 * RATE
    assert len(shift.segments) == 1
    assert shift.segments[0].multiplier == 1.0
    assert shift.work_date == dt.date(2026, 6, 9)


def test_month_status_totals_and_remaining(session, user, cal):
    _add(session, user, cal, local(2026, 6, 9, 9), local(2026, 6, 9, 15))    # 6h @100%
    _add(session, user, cal, local(2026, 6, 10, 9), local(2026, 6, 10, 13))  # 4h @100%

    st = ceiling_mod.month_status(session, user, 2026, 6)
    assert st.shift_count == 2
    assert st.total_hours == 10.0
    assert st.earned_agorot == 10 * RATE
    assert st.ceiling_agorot == DEFAULT_CEILING_AGOROT
    assert st.remaining_agorot == DEFAULT_CEILING_AGOROT - 100_000
    assert not st.over_ceiling
    assert st.remaining_base_hours == pytest.approx(91.13, abs=0.01)
    # The same headroom buys fewer Shabbat hours, since they cost 150%.
    assert st.remaining_rest_hours == pytest.approx(60.75, abs=0.01)


def test_shabbat_hours_are_bucketed_separately(session, user, cal):
    _add(session, user, cal, local(2026, 9, 18, 18), local(2026, 9, 18, 23))
    st = ceiling_mod.month_status(session, user, 2026, 9)

    kinds = {t.kind for t in st.tiers}
    assert kinds == {"day", "shabbat"}
    rest = next(t for t in st.tiers if t.kind == "shabbat")
    assert rest.multiplier == 1.5
    assert rest.hours == pytest.approx(3.0, abs=0.01)


def test_shifts_are_attributed_to_the_month_they_started_in(session, user, cal):
    # 30 June 22:00 -> 1 July 04:00 belongs entirely to June.
    _add(session, user, cal, local(2026, 6, 30, 22), local(2026, 7, 1, 4))
    assert ceiling_mod.month_status(session, user, 2026, 6).total_hours == 6.0
    assert ceiling_mod.month_status(session, user, 2026, 7).shift_count == 0


def test_going_over_the_ceiling_is_reported(session, user, cal):
    # 17 ordinary days x 6h at 100 NIS = 10,200 NIS, just past the 10,113 ceiling.
    for day in workdays(cal, 2026, 6, 17):
        _add(session, user, cal, local(2026, 6, day, 8), local(2026, 6, day, 14))
    st = ceiling_mod.month_status(session, user, 2026, 6)
    assert st.earned_agorot == 17 * 6 * RATE
    assert st.over_ceiling
    assert st.remaining_agorot < 0
    assert st.remaining_base_hours == 0.0  # clamped, never negative hours


def test_alert_thresholds_fire_once_each(session, user, cal):
    # 14 ordinary days x 6h = 8,400 NIS, about 83% of the ceiling.
    for day in workdays(cal, 2026, 6, 14):
        _add(session, user, cal, local(2026, 6, day, 8), local(2026, 6, day, 14))
    st = ceiling_mod.month_status(session, user, 2026, 6)
    assert st.earned_agorot == 14 * 6 * RATE
    assert 80 <= st.pct < 90

    assert ceiling_mod.crossed_threshold(st, already_alerted_pct=0) == 80
    # Once recorded, the same threshold must not fire again.
    assert ceiling_mod.crossed_threshold(st, already_alerted_pct=80) is None


def test_a_raise_does_not_reprice_past_shifts(session, user, cal):
    old = _add(session, user, cal, local(2026, 6, 9, 9), local(2026, 6, 9, 15))
    assert old.total_agorot == 6 * RATE

    repo.set_rate(session, user.id, 12_000, dt.date(2026, 7, 1))
    session.flush()

    assert repo.effective_rate(session, user.id, dt.date(2026, 6, 9)) == RATE
    assert repo.effective_rate(session, user.id, dt.date(2026, 7, 5)) == 12_000
    assert ceiling_mod.month_status(session, user, 2026, 6).earned_agorot == 6 * RATE

    new = _add(session, user, cal, local(2026, 7, 6, 9), local(2026, 7, 6, 15))
    assert new.total_agorot == 6 * 12_000


def test_overlapping_shifts_are_detected(session, user, cal):
    _add(session, user, cal, local(2026, 6, 9, 9), local(2026, 6, 9, 15))

    clash = repo.overlapping_shift(
        session, user.id,
        tu.to_utc_naive(local(2026, 6, 9, 14)), tu.to_utc_naive(local(2026, 6, 9, 18)),
    )
    assert clash is not None

    clear = repo.overlapping_shift(
        session, user.id,
        tu.to_utc_naive(local(2026, 6, 9, 15)), tu.to_utc_naive(local(2026, 6, 9, 18)),
    )
    assert clear is None, "a shift starting exactly when another ends is not an overlap"


def test_deleting_a_shift_removes_its_segments_and_total(session, user, cal):
    from salary_bot.core.models import ShiftSegment

    # 20:00-02:00 crosses the 22:00 night boundary, so it stores two segments.
    shift = _add(session, user, cal, local(2026, 6, 9, 20), local(2026, 6, 10, 2))
    shift_id = shift.id
    assert session.query(ShiftSegment).filter_by(shift_id=shift_id).count() == 2

    repo.delete_shift(session, shift)
    session.flush()

    assert session.query(ShiftSegment).filter_by(shift_id=shift_id).count() == 0
    assert ceiling_mod.month_status(session, user, 2026, 6).earned_agorot == 0


def test_projection_estimates_a_crossing_date(session, user, cal):
    # 1-5 June 2026 are Mon-Fri; the first Saturday is the 6th.
    days = workdays(cal, 2026, 6, 5)
    assert days == [1, 2, 3, 4, 5]
    for day in days:
        _add(session, user, cal, local(2026, 6, day, 8), local(2026, 6, day, 14))
    st = ceiling_mod.month_status(session, user, 2026, 6)
    assert st.earned_agorot == 30 * RATE  # 3,000 NIS

    # 600 NIS/day, 7,113 NIS of headroom -> about 12 more days.
    crossing = st.projected_crossing_date(today=dt.date(2026, 6, 5))
    assert crossing == dt.date(2026, 6, 17)


def test_projection_is_absent_when_the_pace_would_not_reach_the_ceiling(session, user, cal):
    _add(session, user, cal, local(2026, 6, 1, 8), local(2026, 6, 1, 10))  # 2h all month
    st = ceiling_mod.month_status(session, user, 2026, 6)
    assert st.projected_crossing_date(today=dt.date(2026, 6, 10)) is None


def test_reprice_all_applies_the_current_rules(session, user, cal):
    """Segments are stored, so a rules change leaves old shifts on old numbers.
    That is deliberate for auditability — but when the rules were wrong, the
    user needs a correction."""
    shift = _add(session, user, cal, local(2026, 6, 10, 20), local(2026, 6, 11, 2))
    assert shift.total_agorot == 2 * RATE + 4 * NIGHT_RATE  # 2h day band + 4h night band

    # Simulate a flat-rate arrangement being switched on after the fact.
    user.apply_overtime = False
    session.flush()

    count = repo.reprice_all(session, user, cal)
    assert count == 1

    session.refresh(shift)
    assert shift.total_agorot == 6 * RATE, "the night rate should no longer apply"
    assert len(shift.segments) == 1
    assert ceiling_mod.month_status(session, user, 2026, 6).earned_agorot == 6 * RATE


def test_reprice_all_follows_a_rate_change(session, user, cal):
    shift = _add(session, user, cal, local(2026, 6, 10, 20), local(2026, 6, 11, 2))
    assert shift.total_agorot == 2 * RATE + 4 * NIGHT_RATE

    # A correction to the rates themselves, backdated over the shift.
    repo.set_rate(session, user.id, RATE * 2, dt.date(2000, 1, 1), NIGHT_RATE * 2)
    session.flush()
    repo.reprice_all(session, user, cal)

    session.refresh(shift)
    assert shift.total_agorot == 2 * (2 * RATE) + 4 * (2 * NIGHT_RATE)


def test_reprice_all_ignores_an_open_shift(session, user, cal):
    _add(session, user, cal, local(2026, 6, 9, 9), local(2026, 6, 9, 15))
    repo.start_shift(session, user.id, tu.to_utc_naive(local(2026, 6, 11, 9)))
    session.flush()

    assert repo.reprice_all(session, user, cal) == 1  # the open one is skipped
