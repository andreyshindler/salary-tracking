"""Bot-layer tests: rendering real records, and checking no button is dead."""
from __future__ import annotations

import os
import re

import pytest
from telegram.ext import CallbackQueryHandler

from salary_bot.bot import formatting as fmt
from salary_bot.bot import keyboards as kb
from salary_bot.core import ceiling as ceiling_mod
from tests.conftest import local


# ------------------------------------------------------------------ rendering

def test_money_and_hours_formatting():
    assert fmt.fmt_money(1_011_300) == "₪10,113"
    assert fmt.fmt_money(70_350) == "₪703.50"
    assert fmt.fmt_money(0) == "₪0"
    assert fmt.fmt_money(-5_000) == "-₪50"

    assert fmt.fmt_hours(5.0) == "5"
    assert fmt.fmt_hours(5.5) == "5.5"
    assert fmt.fmt_hours(2.45) == "2.45"


def test_progress_bar_is_clamped():
    assert fmt.progress_bar(0) == "░" * 20
    assert fmt.progress_bar(100) == "▓" * 20
    assert fmt.progress_bar(150) == "▓" * 20        # over the ceiling
    assert fmt.progress_bar(50).count("▓") == 10


def test_hebrew_day_names_map_correctly():
    import datetime as dt

    assert fmt.day_name(dt.date(2026, 9, 18)) == "שישי"
    assert fmt.day_name(dt.date(2026, 9, 19)) == "שבת"
    assert fmt.day_name(dt.date(2026, 9, 20)) == "ראשון"


def test_shift_card_shows_the_shabbat_split(session, user, cal, add_shift):
    shift = add_shift(local(2026, 9, 18, 16), local(2026, 9, 18, 21, 30))
    status = ceiling_mod.month_status(session, user, 2026, 9)
    card = fmt.shift_card(shift, cal, status)

    assert "שישי, 18.09.2026" in card
    assert "16:00–21:30" in card
    assert "100%" in card and "150%" in card
    assert "🕯 שבת" in card
    assert "18:27" in card                      # the candle-lighting split point
    assert fmt.fmt_money(shift.total_agorot) in card
    assert "₪10,113" in card                    # the ceiling still shown
    assert "▓" in card and "░" in card


def test_status_card_renders_with_no_shifts(session, user):
    status = ceiling_mod.month_status(session, user, 2026, 9)
    card = fmt.status_card(status)
    assert "ספטמבר 2026" in card
    assert "₪10,113" in card


def test_status_card_lists_tiers(session, user, add_shift):
    add_shift(local(2026, 6, 9, 8), local(2026, 6, 9, 20))  # 12h -> three tiers
    status = ceiling_mod.month_status(session, user, 2026, 6)
    card = fmt.status_card(status)
    for pct in ("100%", "125%", "150%"):
        assert pct in card


def test_forecast_card_handles_the_no_rate_case(session, user, add_shift):
    from salary_bot.core import repo
    import datetime as dt

    repo.set_rate(session, user.id, 0, dt.date(2000, 1, 1))
    session.flush()
    status = ceiling_mod.month_status(session, user, 2026, 6)
    assert "תעריף" in fmt.forecast_card(status)


def test_rtl_mark_is_prefixed_to_numeric_lines(session, user, cal, add_shift):
    """Lines starting with a digit need the RTL mark or Telegram lays the whole
    paragraph out left-to-right and scatters the Hebrew."""
    shift = add_shift(local(2026, 9, 18, 16), local(2026, 9, 18, 21, 30))
    breakdown = fmt.shift_breakdown(shift, cal)
    for line in breakdown.splitlines():
        assert line.startswith("‏"), f"missing RTL mark: {line!r}"


# -------------------------------------------------------------------- wiring

@pytest.fixture(scope="module")
def application(tmp_path_factory):
    os.environ["BOT_TOKEN"] = "123456:FAKE-TOKEN-FOR-TESTS"
    os.environ["ALLOWED_USER_IDS"] = "111"
    os.environ["DB_PATH"] = str(tmp_path_factory.mktemp("botdb") / "t.db")

    from salary_bot.bot import main as bot_main
    from salary_bot.bot.handlers import common
    from salary_bot.config import load_config
    from salary_bot.core import db

    config = load_config()
    db.init_engine(config.db_url)
    common.set_config(config)
    return bot_main.build_application(config)


def _all_callback_data() -> set[str]:
    """Every callback_data the bot can put in front of the user."""
    markups = [
        kb.main_menu(True), kb.main_menu(False),
        kb.back_only(), kb.cancel_only(),
        kb.after_shift(7), kb.confirm_delete(7), kb.shift_detail(7, "ls:2026:6"),
        kb.month_list([(2026, 9), (2026, 6)], None),
        kb.reports_menu(), kb.settings_menu(),
        kb.city_picker("tel_aviv"),
        kb.overtime_menu(True, 8.0), kb.overtime_menu(False, 8.0),
        kb.notifications_menu(True, False, True),
        kb.onboarding(True), kb.onboarding(False),
    ]
    data = set()
    for markup in markups:
        for row in markup.inline_keyboard:
            for button in row:
                if button.callback_data:
                    data.add(button.callback_data)
    return data


def test_every_button_has_a_handler(application):
    """A typo in callback_data produces a button that silently does nothing;
    this catches that at build time rather than in the user's hands."""
    patterns = [
        h.pattern
        for group in application.handlers.values()
        for h in group
        if isinstance(h, CallbackQueryHandler) and h.pattern is not None
    ]
    assert patterns, "no callback handlers registered"

    unrouted = [
        data for data in sorted(_all_callback_data())
        if not any(re.search(p, data) for p in patterns)
    ]
    assert not unrouted, f"buttons with no handler: {unrouted}"


def test_dynamic_shift_callbacks_are_routed(application):
    """The list screen builds callbacks from database ids at runtime."""
    patterns = [
        h.pattern
        for group in application.handlers.values()
        for h in group
        if isinstance(h, CallbackQueryHandler) and h.pattern is not None
    ]
    for data in ["ls:2026:9", "sd:123", "del:123", "delok:123", "setcity:jerusalem", "notif:open"]:
        assert any(re.search(p, data) for p in patterns), f"unrouted: {data}"


def test_commands_are_declared(application):
    from salary_bot.bot.main import COMMANDS

    names = {c.command for c in COMMANDS}
    assert {"start", "shift", "status", "add", "report", "settings", "undo", "help"} == names
    for command in COMMANDS:
        assert command.description, f"/{command.command} has no description"
