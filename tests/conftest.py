import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from salary_bot.core import db, repo
from salary_bot.core.calendar_service import CalendarService

IL = ZoneInfo("Asia/Jerusalem")
# Deliberately far apart so any amount reveals which base rate was applied.
RATE = 10_000        # day rate: 100.00 NIS/hour, in agorot
NIGHT_RATE = 20_000  # night rate: 200.00 NIS/hour


def local(y, m, d, hh, mm=0) -> dt.datetime:
    return dt.datetime(y, m, d, hh, mm, tzinfo=IL)


def workdays(cal: CalendarService, year: int, month: int, count: int) -> list[int]:
    """First ``count`` ordinary working days of a month, as day numbers.

    Tests that assert round shekel totals must avoid Shabbat and holidays, or
    the 150% premium silently changes the arithmetic. Skipping them here keeps
    the expected numbers in those tests obvious.
    """
    days: list[int] = []
    day = 1
    while len(days) < count:
        candidate = dt.date(year, month, day)
        if not cal.is_rest_day(candidate):
            days.append(day)
        day += 1
    return days


@pytest.fixture(scope="session")
def cal_tlv() -> CalendarService:
    return CalendarService("tel_aviv")


@pytest.fixture()
def cal() -> CalendarService:
    return CalendarService("tel_aviv")


@pytest.fixture()
def session(tmp_path):
    db.init_engine(f"sqlite:///{tmp_path/'test.db'}")
    with db.session_scope() as s:
        yield s


@pytest.fixture()
def user(session):
    u = db.get_or_create_user(session, tg_user_id=42)
    repo.set_rate(session, u.id, RATE, dt.date(2000, 1, 1), NIGHT_RATE)
    session.flush()
    return u


@pytest.fixture()
def add_shift(session, user, cal):
    """Record a shift from local aware datetimes."""
    from salary_bot.core import timeutil as tu

    def _add(start, end):
        return repo.add_manual_shift(
            session, user, tu.to_utc_naive(start), tu.to_utc_naive(end), cal
        )

    return _add
