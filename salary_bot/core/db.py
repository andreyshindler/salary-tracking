"""Database session management.

Deliberately synchronous SQLAlchemy inside an async bot. For a single-user
SQLite bot the queries are sub-millisecond, so the event-loop blocking is
irrelevant, and sync sessions keep the handlers far easier to read.
"""
from __future__ import annotations

import datetime as dt
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from ..config import DEFAULT_CEILING_AGOROT, DEFAULT_CITY
from .models import Base, Ceiling, Rate, User

_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def init_engine(db_url: str) -> None:
    global _engine, _SessionLocal
    _engine = create_engine(db_url, future=True)

    @event.listens_for(_engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        # WAL keeps reads from blocking the writer; the bot reads on every render.
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(_engine)
    _ensure_columns()
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)


# Columns added after the first release. create_all() only creates missing
# *tables*, so an existing database would keep the old shape and every query
# touching one of these would fail. Each entry must carry a DEFAULT: SQLite
# cannot add a NOT NULL column without one.
_ADDED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "users": [
        ("status", "VARCHAR(16) NOT NULL DEFAULT 'pending'"),
        ("is_admin", "BOOLEAN NOT NULL DEFAULT 0"),
        ("access_notified", "BOOLEAN NOT NULL DEFAULT 0"),
        ("tg_username", "VARCHAR(64)"),
        ("tg_first_name", "VARCHAR(128)"),
        ("night_start_min", "INTEGER NOT NULL DEFAULT 1320"),  # 22:00
        ("night_end_min", "INTEGER NOT NULL DEFAULT 480"),     # 08:00
    ],
}


def _ensure_columns() -> None:
    """Additive, idempotent migration for columns introduced after release.

    Deliberately additive only — nothing is dropped or retyped, so it is safe to
    run on every startup and cannot lose data.
    """
    with _engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            present = {
                row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")
            }
            if not present:
                continue  # table not created yet; create_all will have made it
            for name, ddl in columns:
                if name not in present:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


@contextmanager
def session_scope() -> Iterator[Session]:
    if _SessionLocal is None:
        raise RuntimeError("init_engine() must be called before opening a session")
    s = _SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_or_create_user(
    s: Session,
    tg_user_id: int,
    username: str | None = None,
    first_name: str | None = None,
) -> User:
    """Fetch the user, creating them with sensible defaults on first contact.

    A row is created even for someone with no access yet: that row *is* the
    pending access request. Access is decided by ``status``, never by the mere
    existence of the record.
    """
    user = s.query(User).filter_by(tg_user_id=tg_user_id).one_or_none()
    if user is not None:
        # Names change; keep them fresh so the admin's approval screen is not
        # showing a handle from months ago.
        if username is not None and user.tg_username != username:
            user.tg_username = username
        if first_name is not None and user.tg_first_name != first_name:
            user.tg_first_name = first_name
        return user

    user = User(
        tg_user_id=tg_user_id,
        city=DEFAULT_CITY,
        tg_username=username,
        tg_first_name=first_name,
    )
    s.add(user)
    s.flush()

    epoch = dt.date(2000, 1, 1)
    # Rate starts at zero: the bot prompts for it during onboarding, and a zero
    # rate makes "you haven't set your rate yet" obvious instead of silently
    # pricing everything at some invented default.
    s.add(Rate(user_id=user.id, hourly_agorot=0, effective_from=epoch))
    s.add(Ceiling(user_id=user.id, amount_agorot=DEFAULT_CEILING_AGOROT, effective_from=epoch))
    s.flush()
    return user
