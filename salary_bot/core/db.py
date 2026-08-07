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
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)


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


def get_or_create_user(s: Session, tg_user_id: int) -> User:
    """Fetch the user, creating them with sensible defaults on first contact."""
    user = s.query(User).filter_by(tg_user_id=tg_user_id).one_or_none()
    if user is not None:
        return user

    user = User(tg_user_id=tg_user_id, city=DEFAULT_CITY)
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
