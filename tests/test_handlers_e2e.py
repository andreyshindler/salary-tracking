"""Drive the handlers with stub Telegram objects.

Compiling and wiring prove the handlers exist; only calling them proves they
run. These catch the failures that matter in practice — a detached SQLAlchemy
attribute touched after the session closed, a format placeholder that does not
exist, a keyboard built from the wrong variable.
"""
from __future__ import annotations

import datetime as dt

import pytest

from salary_bot.bot import formatting as fmt
from salary_bot.bot.handlers import common, manual, reports, settings, shift, text_input
from salary_bot.core import db, repo
from salary_bot.core import timeutil as tu
from tests.conftest import NIGHT_RATE, RATE

from tests.stubs import TG_ID, FakeContext, FakeUpdate, last_output


# ------------------------------------------------------------------- fixtures

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


# --------------------------------------------------------------------- tests

@pytest.mark.asyncio
async def test_a_stranger_cannot_reach_the_handlers(bot_env, ctx):
    """The access flow itself is covered in test_access.py; this only pins that
    an unapproved user never reaches the feature handlers."""
    update = FakeUpdate(text="10/06/2026 09:00 15:00", user_id=999)
    await text_input.route(update, ctx)

    out = last_output(update)
    assert "סה״כ המשמרת" not in out
    assert "999" in out  # told their ID so the admin can be given it


@pytest.mark.asyncio
async def test_start_command_renders_the_main_menu(bot_env, ctx):
    update = FakeUpdate(text="/start")
    await common.cmd_start(update, ctx)
    assert update.message.replies
    markup = update.message.replies[-1][1]
    assert markup is not None


@pytest.mark.asyncio
async def test_start_takes_away_the_old_reply_keyboard(bot_env, ctx):
    """An earlier version left a 📅 פתיחת היומן button under the input field,
    and Telegram keeps one until a message removes it."""
    from telegram import ReplyKeyboardRemove

    await common.cmd_start(FakeUpdate(text="/start"), ctx)

    removals = [m for m in ctx.bot.sent
                if isinstance(m["reply_markup"], ReplyKeyboardRemove)]
    assert len(removals) == 1, "the removal must actually be sent"


@pytest.mark.asyncio
async def test_the_keyboard_removal_is_sent_only_once(bot_env, ctx):
    """It carries an explanation, so repeating it on every menu would nag."""
    from telegram import ReplyKeyboardRemove

    for _ in range(3):
        await common.cmd_start(FakeUpdate(text="/start"), ctx)
        await common.cb_main(FakeUpdate(callback="m:main"), ctx)

    removals = [m for m in ctx.bot.sent
                if isinstance(m["reply_markup"], ReplyKeyboardRemove)]
    assert len(removals) == 1, [m["text"] for m in removals]


@pytest.mark.asyncio
async def test_help_renders_the_rate_table(bot_env, ctx):
    update = FakeUpdate(text="/help")
    await common.cmd_help(update, ctx)
    text = last_output(update)
    assert "חול המועד" in text
    for expected in ("100%", "125%", "150%", "200%", "08:00–22:00", "22:00–05:00"):
        assert expected in text, expected


@pytest.mark.asyncio
async def test_start_then_stop_a_live_shift(bot_env, ctx):
    start = FakeUpdate(callback="sh:start")
    await shift.cb_start(start, ctx)
    assert "המשמרת התחילה" in last_output(start)

    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        open_shift = repo.open_shift(s, user.id)
        assert open_shift is not None
        # Backdate it so the closed shift has real duration.
        open_shift.start_utc = tu.now_utc() - dt.timedelta(hours=3)

    stop = FakeUpdate(callback="sh:stop")
    await shift.cb_stop(stop, ctx)
    card = last_output(stop)
    assert "סה״כ המשמרת" in card
    assert "₪10,113" in card  # the ceiling block is attached

    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        assert repo.open_shift(s, user.id) is None


@pytest.mark.asyncio
async def test_starting_twice_is_refused(bot_env, ctx):
    await shift.cb_start(FakeUpdate(callback="sh:start"), ctx)
    second = FakeUpdate(callback="sh:start")
    await shift.cb_start(second, ctx)
    assert "כבר יש לך משמרת פתוחה" in last_output(second)


@pytest.mark.asyncio
async def test_cancelling_an_open_shift_records_nothing(bot_env, ctx):
    await shift.cb_start(FakeUpdate(callback="sh:start"), ctx)
    cancel = FakeUpdate(callback="sh:cancel")
    await shift.cb_cancel_open(cancel, ctx)
    assert "בוטלה" in last_output(cancel)

    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        assert repo.open_shift(s, user.id) is None
        assert repo.recent_shifts(s, user.id) == []


@pytest.mark.asyncio
async def test_manual_entry_end_to_end(bot_env, ctx):
    ctx.user_data["awaiting"] = "manual"
    # 10 June 2026 is an ordinary Wednesday, so the whole shift is at 100%.
    update = FakeUpdate(text="10/06/2026 16:00 21:30")
    await manual.handle_text(update, ctx)

    card = last_output(update)
    assert "16:00–21:30" in card
    assert "סה״כ המשמרת" in card
    assert "awaiting" not in ctx.user_data

    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        shifts = repo.recent_shifts(s, user.id)
        assert len(shifts) == 1
        assert shifts[0].total_agorot == round(5.5 * RATE)


@pytest.mark.asyncio
async def test_manual_entry_on_a_friday_evening_splits_at_the_shabbat_window(bot_env, ctx):
    ctx.user_data["awaiting"] = "manual"
    update = FakeUpdate(text="18/09/2026 18:00 23:00")
    await manual.handle_text(update, ctx)

    card = last_output(update)
    assert "🕯 שבת" in card
    assert "150%" in card
    assert "20:00" in card          # where the window opens


@pytest.mark.asyncio
async def test_manual_entry_rejects_an_overlap(bot_env, ctx):
    ctx.user_data["awaiting"] = "manual"
    await manual.handle_text(FakeUpdate(text="10/06/2026 09:00 15:00"), ctx)

    ctx.user_data["awaiting"] = "manual"
    clash = FakeUpdate(text="10/06/2026 14:00 18:00")
    await manual.handle_text(clash, ctx)
    assert "חופפת" in last_output(clash)

    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        assert len(repo.recent_shifts(s, user.id)) == 1


@pytest.mark.asyncio
async def test_manual_entry_reports_a_parse_error(bot_env, ctx):
    ctx.user_data["awaiting"] = "manual"
    update = FakeUpdate(text="בלה בלה")
    await manual.handle_text(update, ctx)
    assert "שתי שעות" in last_output(update)


@pytest.mark.asyncio
async def test_status_screen_reflects_logged_hours(bot_env, ctx):
    # The shift must land in the current month, since the status screen reports
    # it — but it must not land on a Shabbat, or the 150% premium changes the
    # total and the test fails purely because of the day it was run on.
    from salary_bot.core.calendar_service import CalendarService
    from tests.conftest import workdays

    now = tu.now_local()
    day = workdays(CalendarService("tel_aviv"), now.year, now.month, 1)[0]

    ctx.user_data["awaiting"] = "manual"
    await manual.handle_text(
        FakeUpdate(text=f"{day:02d}/{now.month:02d}/{now.year} 09:00 15:00"), ctx
    )

    status = FakeUpdate(callback="st:cur")
    await reports.show_status(status, ctx)
    text = last_output(status)
    assert "מצב החודש" in text
    assert "₪600" in text          # 6h at 100 NIS
    assert "נותרו" in text


@pytest.mark.asyncio
async def test_reports_screens_all_render(bot_env, ctx):
    ctx.user_data["awaiting"] = "manual"
    await manual.handle_text(FakeUpdate(text="10/06/2026 08:00 20:00"), ctx)

    for handler in (reports.cb_reports_menu, reports.cb_month_report,
                    reports.cb_tier_report, reports.cb_forecast, reports.cb_year_report):
        update = FakeUpdate(callback="rep:x")
        await handler(update, ctx)
        assert last_output(update)


@pytest.mark.asyncio
async def test_csv_export_produces_a_document(bot_env, ctx):
    ctx.user_data["awaiting"] = "manual"
    await manual.handle_text(FakeUpdate(text="10/06/2026 20:00 08:00"), ctx)

    update = FakeUpdate(callback="rep:csv")
    await reports.cb_export_csv(update, ctx)

    assert len(ctx.bot.documents) == 1
    payload = ctx.bot.documents[0]["document"].input_file_content
    text = payload.decode("utf-8-sig")
    assert "מזהה משמרת" in text
    # One row per priced segment, so every band is itemised separately.
    for expected in ("100%", "125%", "200%", "לילה", "בוקר"):
        assert expected in text, expected


@pytest.mark.asyncio
async def test_settings_screen_and_rate_change(bot_env, ctx):
    menu = FakeUpdate(callback="set:menu")
    await settings.show_menu(menu, ctx)
    assert "תעריף יום" in last_output(menu)

    ask = FakeUpdate(callback="set:rate")
    await settings.cb_ask_rate(ask, ctx)
    assert ctx.user_data["awaiting"] == "rate"

    saved = FakeUpdate(text="37.5 38.5")
    await settings.handle_rate(saved, ctx)
    out = last_output(saved)
    assert "₪37.50" in out and "₪38.50" in out

    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        assert repo.effective_rates(s, user.id, tu.now_local().date()) == (3_750, 3_850)


@pytest.mark.asyncio
async def test_ceiling_change_is_applied(bot_env, ctx):
    update = FakeUpdate(text="12000")
    await settings.handle_ceiling(update, ctx)
    assert "₪12,000" in last_output(update)

    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        assert repo.effective_ceiling(s, user.id, tu.now_local().date()) == 1_200_000


@pytest.mark.asyncio
async def test_overtime_toggle_changes_pricing(bot_env, ctx):
    toggle = FakeUpdate(callback="set:ottoggle")
    await settings.cb_toggle_overtime(toggle, ctx)
    assert "כבוי" in last_output(toggle)

    ctx.user_data["awaiting"] = "manual"
    await manual.handle_text(FakeUpdate(text="10/06/2026 08:00 20:00"), ctx)

    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        assert repo.recent_shifts(s, user.id)[0].total_agorot == 12 * RATE


@pytest.mark.asyncio
async def test_notification_toggles_persist(bot_env, ctx):
    update = FakeUpdate(callback="notif:ceiling")
    await settings.cb_toggle_notification(update, ctx)
    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        assert user.notify_ceiling is False


@pytest.mark.asyncio
async def test_ceiling_alert_fires_once_when_crossing_80_percent(bot_env, ctx):
    """The alert must arrive as its own message, and only on the crossing."""
    from tests.conftest import workdays
    from salary_bot.core.calendar_service import CalendarService

    days = workdays(CalendarService("tel_aviv"), 2026, 6, 14)
    updates = []
    for day in days:
        ctx.user_data["awaiting"] = "manual"
        update = FakeUpdate(text=f"{day:02d}/06/2026 08:00 14:00")
        updates.append(update)
        await manual.handle_text(update, ctx)

    # Manual entry replies in-thread; the live stop button goes through the bot
    # object. Collect both so the assertion does not depend on which path ran.
    emitted = [text for u in updates for text, _ in u.message.replies]
    emitted += [text for _, text in ctx.bot.messages]

    alerts = [t for t in emitted if "מהתקרה" in t or "עברת את התקרה" in t]
    assert len(alerts) == 1, f"expected exactly one ceiling alert, got {len(alerts)}"
    assert "80%" in alerts[0]


@pytest.mark.asyncio
async def test_browsing_shifts_and_deleting_one(bot_env, ctx):
    ctx.user_data["awaiting"] = "manual"
    await manual.handle_text(FakeUpdate(text="10/06/2026 09:00 15:00"), ctx)

    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        shift_id = repo.recent_shifts(s, user.id)[0].id

    months = FakeUpdate(callback="ls:menu")
    await shift.cb_month_list(months, ctx)
    assert "בחר חודש" in last_output(months)

    listing = FakeUpdate(callback="ls:2026:6")
    await shift.cb_shifts_of_month(listing, ctx)
    assert "יוני 2026" in last_output(listing)

    detail = FakeUpdate(callback=f"sd:{shift_id}")
    await shift.cb_shift_detail(detail, ctx)
    assert "משמרת" in last_output(detail)

    prompt = FakeUpdate(callback=f"del:{shift_id}")
    await shift.cb_delete_prompt(prompt, ctx)
    assert "למחוק" in last_output(prompt)

    confirm = FakeUpdate(callback=f"delok:{shift_id}")
    await shift.cb_delete_confirm(confirm, ctx)
    assert "נמחקה" in last_output(confirm)

    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        assert repo.recent_shifts(s, user.id) == []


@pytest.mark.asyncio
async def test_bare_text_is_treated_as_a_shift_entry(bot_env, ctx):
    """No prompt pending: a stray "09:00 15:00" should still log the shift."""
    update = FakeUpdate(text="10/06/2026 09:00 15:00")
    await text_input.route(update, ctx)
    assert "סה״כ המשמרת" in last_output(update)


@pytest.mark.asyncio
async def test_backdated_start_time(bot_env, ctx):
    ask = FakeUpdate(callback="sh:earlier")
    await shift.cb_start_earlier(ask, ctx)
    assert ctx.user_data["awaiting"] == "start_time"

    update = FakeUpdate(text="08:30")
    await text_input.route(update, ctx)

    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        open_shift = repo.open_shift(s, user.id)
        assert open_shift is not None
        assert tu.to_local(open_shift.start_utc).strftime("%H:%M") == "08:30"


@pytest.mark.asyncio
async def test_recalculation_respects_rate_versioning(bot_env, ctx):
    """Recalculation re-applies the *rules*, not today's rates to every shift.

    A new rate takes effect from the first of the current month, so a shift in a
    closed month must keep the rates it was priced at even after a recalculate —
    otherwise a raise would silently restate a month already reported.
    """
    ctx.user_data["awaiting"] = "manual"
    await manual.handle_text(FakeUpdate(text="10/06/2026 20:00 02:00"), ctx)

    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        before = repo.recent_shifts(s, user.id)[0].total_agorot
    assert before == 2 * RATE + 4 * NIGHT_RATE   # 2h day band + 4h night band

    saved = FakeUpdate(text="200 400")
    await settings.handle_rate(saved, ctx)
    assert "₪200" in last_output(saved) and "₪400" in last_output(saved)

    recalc = FakeUpdate(callback="set:recalc")
    await settings.cb_recalculate(recalc, ctx)

    with db.session_scope() as s:
        user = db.get_or_create_user(s, TG_ID)
        assert repo.recent_shifts(s, user.id)[0].total_agorot == before, (
            "a June shift must not be re-priced at rates effective from this month"
        )


@pytest.mark.asyncio
async def test_recalculate_with_no_shifts_says_so(bot_env, ctx):
    update = FakeUpdate(callback="set:recalc")
    await settings.cb_recalculate(update, ctx)
    assert "אין משמרות" in last_output(update)


@pytest.mark.asyncio
async def test_a_night_shift_card_shows_both_base_rates(bot_env, ctx):
    ctx.user_data["awaiting"] = "manual"
    update = FakeUpdate(text="10/06/2026 20:00 02:00")
    await manual.handle_text(update, ctx)

    card = last_output(update)
    assert "🌙" in card
    assert "22:00" in card                                   # the band boundary
    # Both base rates must be visible: the multiplier alone no longer explains
    # the amount now that two rates are in play.
    assert fmt.fmt_money(RATE) in card and fmt.fmt_money(NIGHT_RATE) in card
