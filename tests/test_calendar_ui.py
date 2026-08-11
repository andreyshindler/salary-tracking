"""The calendar picker: the grid itself, and picking a day then entering hours."""
from __future__ import annotations

import datetime as dt

import pytest

from salary_bot.bot import month_grid
from salary_bot.bot.handlers import calendar as cal_handlers
from salary_bot.bot.handlers import common
from salary_bot.core import db, repo
from tests.conftest import NIGHT_RATE, RATE
from tests.stubs import TG_ID, FakeContext, FakeUpdate, callback_data, last_output


@pytest.fixture()
def bot_env(tmp_path):
    from salary_bot.config import Config

    db.init_engine(f"sqlite:///{tmp_path/'bot.db'}")
    common.set_config(Config(
        bot_token="123:FAKE",
        allowed_user_ids=frozenset({TG_ID}),
        db_path=tmp_path / "bot.db",
        log_level="INFO",
    ))
    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        repo.set_rate(s, user.id, RATE, dt.date(2000, 1, 1), NIGHT_RATE)
    return True


@pytest.fixture()
def ctx():
    return FakeContext()


# ------------------------------------------------------------------- the grid

def test_the_grid_is_laid_out_right_to_left():
    """Hebrew calendars put ראשון on the right, and Telegram will not mirror a
    keyboard, so each row is reversed here."""
    markup = month_grid.month_grid(2026, 9, {}, set())
    header = [b.text for b in markup.inline_keyboard[0]]
    assert header == ["ש", "ו", "ה", "ד", "ג", "ב", "א"]

    # 1 Sep 2026 is a Tuesday, so in a Sunday-first week it sits third from the
    # right — index 4 once the row is reversed.
    first_week = markup.inline_keyboard[1]
    assert first_week[4].text == "1"
    assert first_week[6].text.strip() == ""   # Sunday padding, before the 1st


def test_every_day_of_the_month_appears_exactly_once():
    markup = month_grid.month_grid(2026, 2, {}, set())   # 28 days
    days = [
        b.callback_data.split(":")[-1]
        for row in markup.inline_keyboard
        for b in row
        if b.callback_data.startswith("cal:d:")
    ]
    assert sorted(map(int, days)) == list(range(1, 29))


def test_padding_and_headers_are_inert():
    markup = month_grid.month_grid(2026, 9, {}, set())
    for row in markup.inline_keyboard:
        for button in row:
            assert button.callback_data, "every cell needs a callback"
    assert all(b.callback_data == "noop" for b in markup.inline_keyboard[0])


def test_day_labels_carry_their_marks():
    assert month_grid.day_label(5, has_shifts=False, is_chag=False, is_today=False) == "5"
    assert month_grid.day_label(5, has_shifts=True, is_chag=False, is_today=False) == "•5"
    assert month_grid.day_label(5, has_shifts=False, is_chag=True, is_today=False) == "5✡"
    assert month_grid.day_label(5, has_shifts=False, is_chag=False, is_today=True) == "[5]"
    assert month_grid.day_label(5, has_shifts=True, is_chag=True, is_today=True) == "[•5✡]"


def test_navigation_wraps_across_the_year():
    markup = month_grid.month_grid(2026, 1, {}, set())
    nav = callback_data(markup)
    assert "cal:m:2025:12" in nav, "January must step back into December"
    assert "cal:m:2026:2" in nav

    markup = month_grid.month_grid(2026, 12, {}, set())
    assert "cal:m:2027:1" in callback_data(markup)


# ------------------------------------------------------------------ the flow

@pytest.mark.asyncio
async def test_opening_the_calendar_shows_the_current_month(bot_env, ctx):
    update = FakeUpdate(callback="cal:today")
    await cal_handlers.cb_month(update, ctx)

    text, markup = update.callback_query.edits[-1]
    assert "בחר יום" in text
    assert any(d.startswith("cal:d:") for d in callback_data(markup))


@pytest.mark.asyncio
async def test_picking_a_day_and_entering_hours_records_a_shift(bot_env, ctx):
    day = FakeUpdate(callback="cal:d:2026:6:10")
    await cal_handlers.cb_day(day, ctx)
    out = last_output(day)
    assert "10.06.2026" in out
    assert "אין עדיין שעות" in out

    prompt = FakeUpdate(callback="cal:add:2026:6:10")
    await cal_handlers.cb_add_hours(prompt, ctx)
    assert ctx.user_data["awaiting"] == "day_hours"
    assert ctx.user_data["awaiting_arg"] == "2026-06-10"

    entry = FakeUpdate(text="09:00 15:00")
    await cal_handlers.handle_hours(entry, ctx)

    card = last_output(entry)
    assert "סה״כ המשמרת" in card
    assert "awaiting" not in ctx.user_data

    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        shifts = repo.shifts_on_date(s, user.id, dt.date(2026, 6, 10))
        assert len(shifts) == 1
        assert shifts[0].total_agorot == 6 * RATE


@pytest.mark.asyncio
async def test_hours_land_on_the_picked_day_not_today(bot_env, ctx):
    """The whole point of the calendar: a bare "09:00 15:00" must attach to the
    date that was tapped, however long ago it was."""
    ctx.user_data["awaiting"] = "day_hours"
    ctx.user_data["awaiting_arg"] = "2026-03-04"
    await cal_handlers.handle_hours(FakeUpdate(text="09:00 15:00"), ctx)

    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        assert repo.shifts_on_date(s, user.id, dt.date(2026, 3, 4))
        assert not repo.shifts_on_date(s, user.id, dt.date.today())


@pytest.mark.asyncio
async def test_an_overnight_entry_still_rolls_to_the_next_day(bot_env, ctx):
    ctx.user_data["awaiting"] = "day_hours"
    ctx.user_data["awaiting_arg"] = "2026-06-10"
    await cal_handlers.handle_hours(FakeUpdate(text="22:00 04:00"), ctx)

    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        shift = repo.shifts_on_date(s, user.id, dt.date(2026, 6, 10))[0]
        hours = sum(seg.hours for seg in shift.segments)
        assert hours == 6.0


@pytest.mark.asyncio
async def test_a_logged_day_is_marked_in_the_grid(bot_env, ctx):
    ctx.user_data["awaiting"] = "day_hours"
    ctx.user_data["awaiting_arg"] = "2026-06-10"
    await cal_handlers.handle_hours(FakeUpdate(text="09:00 15:00"), ctx)

    grid = FakeUpdate(callback="cal:m:2026:6")
    await cal_handlers.cb_month(grid, ctx)
    _, markup = grid.callback_query.edits[-1]

    marked = [
        b.text for row in markup.inline_keyboard for b in row
        if b.callback_data == "cal:d:2026:6:10"
    ]
    assert marked and marked[0].startswith("•"), marked


@pytest.mark.asyncio
async def test_chag_days_are_marked_before_you_work_them(bot_env, ctx):
    """Rosh Hashana 5787 falls on 12-13 Sep 2026, and חג pays 200%."""
    grid = FakeUpdate(callback="cal:m:2026:9")
    await cal_handlers.cb_month(grid, ctx)
    _, markup = grid.callback_query.edits[-1]

    labels = {
        b.callback_data.split(":")[-1]: b.text
        for row in markup.inline_keyboard for b in row
        if b.callback_data.startswith("cal:d:")
    }
    assert "✡" in labels["12"] and "✡" in labels["13"]
    assert "✡" in labels["21"]           # Yom Kippur
    assert "✡" not in labels["19"]       # an ordinary Shabbat is not chag
    assert "✡" not in labels["10"]


@pytest.mark.asyncio
async def test_the_day_screen_lists_existing_shifts(bot_env, ctx):
    ctx.user_data["awaiting"] = "day_hours"
    ctx.user_data["awaiting_arg"] = "2026-06-10"
    await cal_handlers.handle_hours(FakeUpdate(text="09:00 15:00"), ctx)

    day = FakeUpdate(callback="cal:d:2026:6:10")
    await cal_handlers.cb_day(day, ctx)
    text, markup = day.callback_query.edits[-1]

    assert "סה״כ ליום" in text
    data = callback_data(markup)
    assert any(d.startswith("sd:") for d in data), "the shift should be tappable"
    assert "cal:add:2026:6:10" in data


@pytest.mark.asyncio
async def test_overlapping_hours_are_refused(bot_env, ctx):
    ctx.user_data["awaiting"] = "day_hours"
    ctx.user_data["awaiting_arg"] = "2026-06-10"
    await cal_handlers.handle_hours(FakeUpdate(text="09:00 15:00"), ctx)

    ctx.user_data["awaiting"] = "day_hours"
    ctx.user_data["awaiting_arg"] = "2026-06-10"
    clash = FakeUpdate(text="14:00 18:00")
    await cal_handlers.handle_hours(clash, ctx)
    assert "חופפת" in last_output(clash)

    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        assert len(repo.shifts_on_date(s, user.id, dt.date(2026, 6, 10))) == 1


@pytest.mark.asyncio
async def test_a_bad_entry_reports_the_error_and_keeps_the_prompt(bot_env, ctx):
    ctx.user_data["awaiting"] = "day_hours"
    ctx.user_data["awaiting_arg"] = "2026-06-10"
    bad = FakeUpdate(text="בלה בלה")
    await cal_handlers.handle_hours(bad, ctx)

    assert "שתי שעות" in last_output(bad)
    assert ctx.user_data["awaiting"] == "day_hours", "the prompt should still be live"


@pytest.mark.asyncio
async def test_a_stranger_cannot_open_the_calendar(bot_env, ctx):
    update = FakeUpdate(callback="cal:today", user_id=999)
    await cal_handlers.cb_month(update, ctx)
    assert "999" in last_output(update)
