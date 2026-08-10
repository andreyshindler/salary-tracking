"""Access control: requesting, approving, denying, and who is allowed to decide.

The privilege-escalation cases matter most. Callback data is a string the client
sends back, so hiding a button is not a control — anyone who learns the format
can send `acc:ok:<their own id>`. Those cases are asserted directly.
"""
from __future__ import annotations

import datetime as dt

import pytest

from salary_bot.core import access, db, repo
from salary_bot.bot.handlers import admin, common, manual, settings, shift, text_input
from tests.conftest import RATE
from tests.stubs import FakeContext, FakeUpdate, callback_data, last_output

ADMIN_ID = 111
STRANGER_ID = 777
OTHER_ID = 888


@pytest.fixture()
def bot_env(tmp_path):
    from salary_bot.config import Config

    db.init_engine(f"sqlite:///{tmp_path/'bot.db'}")
    common.set_config(Config(
        bot_token="123:FAKE",
        allowed_user_ids=frozenset({ADMIN_ID}),
        db_path=tmp_path / "bot.db",
        log_level="INFO",
    ))
    return True


@pytest.fixture()
def ctx():
    return FakeContext()


async def _become_admin(ctx):
    """One touch from the env-listed ID promotes it to an approved admin."""
    await common.cmd_start(FakeUpdate(text="/start", user_id=ADMIN_ID), ctx)


def _status(tg_id: str | int) -> str | None:
    with db.session_scope() as s:
        user = access.get_by_tg_id(s, int(tg_id))
        return user.status if user else None


# --------------------------------------------------------------- bootstrapping

@pytest.mark.asyncio
async def test_env_listed_user_is_auto_approved_as_admin(bot_env, ctx):
    await _become_admin(ctx)
    with db.session_scope() as s:
        user = access.get_by_tg_id(s, ADMIN_ID)
        assert user.status == access.APPROVED
        assert user.is_admin is True


@pytest.mark.asyncio
async def test_bootstrap_recovers_an_admin_who_lost_access(bot_env, ctx):
    """Adding an ID back to ALLOWED_USER_IDS must be an escape hatch, so the
    promotion runs on every contact and not only on first creation."""
    await _become_admin(ctx)
    with db.session_scope() as s:
        access.set_status(s, ADMIN_ID, access.DENIED)
    assert _status(ADMIN_ID) == access.DENIED

    await _become_admin(ctx)
    assert _status(ADMIN_ID) == access.APPROVED


# ------------------------------------------------------------ requesting access

@pytest.mark.asyncio
async def test_new_user_is_told_approval_is_needed_and_admin_is_notified(bot_env, ctx):
    await _become_admin(ctx)
    ctx.bot.sent.clear()

    update = FakeUpdate(text="שלום", user_id=STRANGER_ID)
    await text_input.route(update, ctx)

    out = last_output(update)
    assert "אישור" in out                       # approval is needed
    assert str(STRANGER_ID) in out              # and their ID, for the admin
    assert _status(STRANGER_ID) == access.PENDING

    to_admin = [m for m in ctx.bot.sent if m["chat_id"] == ADMIN_ID]
    assert len(to_admin) == 1
    assert str(STRANGER_ID) in to_admin[0]["text"]
    assert set(callback_data(to_admin[0]["reply_markup"])) == {
        f"acc:ok:{STRANGER_ID}", f"acc:no:{STRANGER_ID}",
    }


@pytest.mark.asyncio
async def test_admin_is_notified_only_once_however_many_times_they_ask(bot_env, ctx):
    await _become_admin(ctx)
    ctx.bot.sent.clear()

    for _ in range(4):
        await text_input.route(FakeUpdate(text="שלום", user_id=STRANGER_ID), ctx)

    assert len([m for m in ctx.bot.sent if m["chat_id"] == ADMIN_ID]) == 1


@pytest.mark.asyncio
async def test_repeat_request_says_it_is_still_waiting(bot_env, ctx):
    await _become_admin(ctx)
    await text_input.route(FakeUpdate(text="שלום", user_id=STRANGER_ID), ctx)

    again = FakeUpdate(text="שלום", user_id=STRANGER_ID)
    await text_input.route(again, ctx)
    assert "ממתינה" in last_output(again)


@pytest.mark.asyncio
async def test_a_pending_user_cannot_use_any_feature(bot_env, ctx):
    await _become_admin(ctx)
    await text_input.route(FakeUpdate(text="שלום", user_id=STRANGER_ID), ctx)

    for update, handler in [
        (FakeUpdate(callback="sh:start", user_id=STRANGER_ID), shift.cb_start),
        (FakeUpdate(callback="st:cur", user_id=STRANGER_ID), settings.show_menu),
        (FakeUpdate(text="/add", user_id=STRANGER_ID), manual.cmd_add),
    ]:
        await handler(update, ctx)
        assert "ממתינה" in last_output(update)

    with db.session_scope() as s:
        stranger = access.get_by_tg_id(s, STRANGER_ID)
        assert repo.open_shift(s, stranger.id) is None


# -------------------------------------------------------------------- deciding

@pytest.mark.asyncio
async def test_admin_approves_and_the_user_gains_access(bot_env, ctx):
    await _become_admin(ctx)
    await text_input.route(FakeUpdate(text="שלום", user_id=STRANGER_ID), ctx)
    ctx.bot.sent.clear()

    decision = FakeUpdate(callback=f"acc:ok:{STRANGER_ID}", user_id=ADMIN_ID)
    await admin.cb_decide(decision, ctx)

    assert _status(STRANGER_ID) == access.APPROVED
    # The requester is told, not left waiting silently.
    notice = [m for m in ctx.bot.sent if m["chat_id"] == STRANGER_ID]
    assert len(notice) == 1
    assert "גישה" in notice[0]["text"]

    # And can now actually use the bot.
    with db.session_scope() as s:
        stranger = access.get_by_tg_id(s, STRANGER_ID)
        repo.set_rate(s, stranger.id, RATE, dt.date(2000, 1, 1))

    ctx.user_data["awaiting"] = "manual"
    entry = FakeUpdate(text="10/06/2026 09:00 15:00", user_id=STRANGER_ID)
    await manual.handle_text(entry, ctx)
    assert "סה״כ המשמרת" in last_output(entry)


@pytest.mark.asyncio
async def test_admin_denies_and_the_user_stays_out(bot_env, ctx):
    await _become_admin(ctx)
    await text_input.route(FakeUpdate(text="שלום", user_id=STRANGER_ID), ctx)

    await admin.cb_decide(
        FakeUpdate(callback=f"acc:no:{STRANGER_ID}", user_id=ADMIN_ID), ctx
    )
    assert _status(STRANGER_ID) == access.DENIED

    blocked = FakeUpdate(text="שלום", user_id=STRANGER_ID)
    await text_input.route(blocked, ctx)
    assert "אין לך גישה" in last_output(blocked)


@pytest.mark.asyncio
async def test_revoking_access_also_strips_admin_rights(bot_env, ctx):
    await _become_admin(ctx)
    with db.session_scope() as s:
        db.get_or_create_user(s, OTHER_ID)
        access.set_status(s, OTHER_ID, access.APPROVED)
        access.get_by_tg_id(s, OTHER_ID).is_admin = True

    await admin.cb_decide(
        FakeUpdate(callback=f"acc:rev:{OTHER_ID}", user_id=ADMIN_ID), ctx
    )
    with db.session_scope() as s:
        user = access.get_by_tg_id(s, OTHER_ID)
        assert user.status == access.DENIED
        assert user.is_admin is False


# -------------------------------------------------------- privilege escalation

@pytest.mark.asyncio
async def test_an_approved_non_admin_cannot_approve_anyone(bot_env, ctx):
    """The escalation that matters: a legitimate user forging an admin callback."""
    await _become_admin(ctx)
    with db.session_scope() as s:
        db.get_or_create_user(s, OTHER_ID)
        access.set_status(s, OTHER_ID, access.APPROVED)

    await text_input.route(FakeUpdate(text="שלום", user_id=STRANGER_ID), ctx)

    attempt = FakeUpdate(callback=f"acc:ok:{STRANGER_ID}", user_id=OTHER_ID)
    await admin.cb_decide(attempt, ctx)

    assert _status(STRANGER_ID) == access.PENDING, "a non-admin approved someone"
    assert attempt.callback_query.alerts, "the attempt was not refused"


@pytest.mark.asyncio
async def test_a_pending_user_cannot_approve_themselves(bot_env, ctx):
    await _become_admin(ctx)
    await text_input.route(FakeUpdate(text="שלום", user_id=STRANGER_ID), ctx)

    attempt = FakeUpdate(callback=f"acc:ok:{STRANGER_ID}", user_id=STRANGER_ID)
    await admin.cb_decide(attempt, ctx)
    assert _status(STRANGER_ID) == access.PENDING, "a pending user self-approved"


@pytest.mark.asyncio
async def test_a_pending_user_cannot_list_users(bot_env, ctx):
    await _become_admin(ctx)
    await text_input.route(FakeUpdate(text="שלום", user_id=STRANGER_ID), ctx)

    attempt = FakeUpdate(callback="acc:list", user_id=STRANGER_ID)
    await admin.cb_list(attempt, ctx)
    assert "ממתינה" in last_output(attempt)


@pytest.mark.asyncio
async def test_admin_cannot_revoke_their_own_access(bot_env, ctx):
    """Self-revocation would lock the only admin out with no route back except
    editing the environment and recreating the container."""
    await _become_admin(ctx)

    attempt = FakeUpdate(callback=f"acc:rev:{ADMIN_ID}", user_id=ADMIN_ID)
    await admin.cb_decide(attempt, ctx)
    assert _status(ADMIN_ID) == access.APPROVED


# --------------------------------------------------------------- admin surface

@pytest.mark.asyncio
async def test_users_entry_is_shown_to_admins_only(bot_env, ctx):
    await _become_admin(ctx)
    with db.session_scope() as s:
        db.get_or_create_user(s, OTHER_ID)
        access.set_status(s, OTHER_ID, access.APPROVED)

    as_admin = FakeUpdate(callback="set:menu", user_id=ADMIN_ID)
    await settings.show_menu(as_admin, ctx)
    assert "acc:list" in callback_data(as_admin.callback_query.edits[-1][1])

    as_user = FakeUpdate(callback="set:menu", user_id=OTHER_ID)
    await settings.show_menu(as_user, ctx)
    assert "acc:list" not in callback_data(as_user.callback_query.edits[-1][1])


@pytest.mark.asyncio
async def test_users_screen_lists_pending_requests(bot_env, ctx):
    await _become_admin(ctx)
    await text_input.route(FakeUpdate(text="שלום", user_id=STRANGER_ID), ctx)

    listing = FakeUpdate(callback="acc:list", user_id=ADMIN_ID)
    await admin.cb_list(listing, ctx)

    data = callback_data(listing.callback_query.edits[-1][1])
    assert f"acc:ok:{STRANGER_ID}" in data
    assert f"acc:no:{STRANGER_ID}" in data


# ------------------------------------------------------------- data isolation

@pytest.mark.asyncio
async def test_two_approved_users_have_separate_data(bot_env, ctx):
    """Approving people makes this genuinely multi-user, so one person's hours
    must never appear in another's totals."""
    await _become_admin(ctx)
    with db.session_scope() as s:
        for tg_id in (ADMIN_ID, OTHER_ID):
            user = db.get_or_create_user(s, tg_id)
            access.set_status(s, tg_id, access.APPROVED)
            repo.set_rate(s, user.id, RATE, dt.date(2000, 1, 1))

    ctx.user_data["awaiting"] = "manual"
    await manual.handle_text(
        FakeUpdate(text="10/06/2026 09:00 15:00", user_id=ADMIN_ID), ctx)

    other_ctx = FakeContext()
    other_ctx.user_data["awaiting"] = "manual"
    await manual.handle_text(
        FakeUpdate(text="11/06/2026 09:00 12:00", user_id=OTHER_ID), other_ctx)

    with db.session_scope() as s:
        a = access.get_by_tg_id(s, ADMIN_ID)
        b = access.get_by_tg_id(s, OTHER_ID)
        a_shifts = repo.recent_shifts(s, a.id)
        b_shifts = repo.recent_shifts(s, b.id)

    assert len(a_shifts) == 1 and len(b_shifts) == 1
    assert a_shifts[0].total_agorot == 6 * RATE
    assert b_shifts[0].total_agorot == 3 * RATE


# ------------------------------------------------------------------ migration

def test_missing_columns_are_added_to_an_existing_database(tmp_path):
    """create_all() cannot alter an existing table, so a database written by the
    previous release must be upgraded in place rather than needing a wipe."""
    import sqlalchemy as sa

    path = tmp_path / "old.db"
    engine = sa.create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        # The users table as it existed before access control.
        conn.exec_driver_sql(
            "CREATE TABLE users ("
            " id INTEGER PRIMARY KEY, tg_user_id INTEGER, city VARCHAR(32),"
            " created_at DATETIME, daily_ot_threshold FLOAT, apply_overtime BOOLEAN,"
            " notify_open_shift BOOLEAN, notify_ceiling BOOLEAN,"
            " notify_month_summary BOOLEAN, last_alert_pct INTEGER,"
            " last_alert_month VARCHAR(7))"
        )
        conn.exec_driver_sql("INSERT INTO users (id, tg_user_id) VALUES (1, 555)")
    engine.dispose()

    db.init_engine(f"sqlite:///{path}")
    with db.session_scope() as s:
        user = access.get_by_tg_id(s, 555)
        assert user is not None, "the existing row survived the migration"
        assert user.status == access.PENDING
        assert user.is_admin is False
