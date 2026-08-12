"""Upgrading a database written by an earlier release.

``create_all`` creates missing tables but never alters existing ones, so a
column added after a release would be missing on exactly the databases that
matter — the ones with real data in them. The additive migration in ``db`` runs
on every startup; these tests are what say it works.
"""
from __future__ import annotations

import datetime as dt

import pytest

from salary_bot.core import db, repo
from salary_bot.core.models import User

# Columns added after the first release. Dropping them reproduces the shape of
# a database that predates them.
ADDED_TO_USERS = [name for name, _ in db._ADDED_COLUMNS["users"]]

# What the `users` table looked like when the bot was first deployed. A frozen
# historical record, not something to update: every column added since must be
# in _ADDED_COLUMNS instead, or databases created before it will not get it.
FIRST_RELEASE_USER_COLUMNS = {
    "id", "tg_user_id", "city", "created_at",
    "apply_overtime", "daily_ot_threshold",
    "notify_open_shift", "notify_ceiling", "notify_month_summary",
    "last_alert_pct", "last_alert_month",
}


def columns(table: str) -> set[str]:
    with db._engine.begin() as conn:
        return {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}


@pytest.fixture()
def old_database(tmp_path):
    """A database carrying data, with the newer columns taken back off."""
    url = f"sqlite:///{tmp_path/'old.db'}"
    db.init_engine(url)
    with db.session_scope() as s:
        user = db.get_or_create_user(s, 4242)
        repo.set_rate(s, user.id, 3750, dt.date(2000, 1, 1), 3850)

    with db._engine.begin() as conn:
        # SQLite refuses to drop an indexed column, so the index goes first —
        # a database predating the column would not have had it either.
        conn.exec_driver_sql("DROP INDEX IF EXISTS ix_users_status")
        for name in ADDED_TO_USERS:
            conn.exec_driver_sql(f"ALTER TABLE users DROP COLUMN {name}")
    assert not (columns("users") & set(ADDED_TO_USERS)), "the setup must really remove them"
    return url


def test_every_column_added_since_release_one_is_migrated():
    """The check with teeth. A column added to the model but not to
    _ADDED_COLUMNS would work perfectly on a fresh database and be missing on
    every existing one — which is the only kind that has data in it.
    """
    declared = set(User.__table__.columns.keys())
    covered = FIRST_RELEASE_USER_COLUMNS | set(ADDED_TO_USERS)
    assert declared <= covered, sorted(declared - covered)


def test_the_added_columns_appear_on_startup(old_database):
    db.init_engine(old_database)
    assert set(ADDED_TO_USERS) <= columns("users")


def test_existing_rows_survive_the_upgrade(old_database):
    db.init_engine(old_database)
    with db.session_scope() as s:
        user = db.get_or_create_user(s, 4242)
        assert repo.effective_rates(s, user.id, dt.date.today()) == (3750, 3850)
        # A defaulted flag must read as "not yet done" rather than NULL, or the
        # first menu render would fail on an existing user.
        assert user.keyboard_cleared is False


def test_the_migration_is_idempotent(old_database):
    """It runs on every startup, so running it twice must be a no-op."""
    db.init_engine(old_database)
    before = columns("users")
    db.init_engine(old_database)
    assert columns("users") == before
