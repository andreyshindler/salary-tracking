"""SQLAlchemy models.

Two conventions worth knowing before reading:

* All money is stored as **integer agorot**, never floats. Floats accumulate
  rounding error, and this bot's whole job is comparing a running total to a
  ceiling — drift there would be silently wrong.
* All timestamps are stored as **naive UTC** datetimes (SQLite has no tz type).
  Convert at the edges with ``core.timeutil``.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    city: Mapped[str] = mapped_column(String(32), default="tel_aviv")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)

    # Access control. Anyone who messages the bot gets a row immediately so the
    # request can be reviewed; only "approved" may actually use it.
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # Whether the admin has already been told about this pending request, so a
    # user tapping repeatedly does not send a notification each time.
    access_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    # Cached from Telegram so the admin sees a name rather than a bare number
    # when deciding.
    tg_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tg_first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Settings live inline: this is a single-user bot, so a separate settings
    # table would be a join for nothing.
    # Night premium window, in minutes from local midnight. Defaults to
    # 22:00-08:00. Kept configurable because the hours are an employment term,
    # not a law.
    night_start_min: Mapped[int] = mapped_column(Integer, default=22 * 60)
    night_end_min: Mapped[int] = mapped_column(Integer, default=8 * 60)
    # Master switch: off means everything is paid at 100%.
    apply_overtime: Mapped[bool] = mapped_column(Boolean, default=True)
    # Legacy from the earlier hours-based overtime model, which no longer
    # exists. Retained only so existing databases keep a valid NOT NULL column.
    daily_ot_threshold: Mapped[float] = mapped_column(Float, default=8.0)

    notify_open_shift: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_ceiling: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_month_summary: Mapped[bool] = mapped_column(Boolean, default=True)

    # Highest ceiling-percentage alert already sent this month, so the bot
    # warns once per threshold instead of on every logged shift.
    last_alert_pct: Mapped[int] = mapped_column(Integer, default=0)
    last_alert_month: Mapped[str] = mapped_column(String(7), default="")

    rates: Mapped[list["Rate"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    ceilings: Mapped[list["Ceiling"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    shifts: Mapped[list["Shift"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Rate(Base):
    """Hourly rate history. A raise must never retroactively re-price old shifts,
    so rates are versioned by effective date and never updated in place."""

    __tablename__ = "rates"
    __table_args__ = (UniqueConstraint("user_id", "effective_from", name="uq_rate_user_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    hourly_agorot: Mapped[int] = mapped_column(Integer)
    effective_from: Mapped[dt.date] = mapped_column(Date)

    user: Mapped[User] = relationship(back_populates="rates")


class Ceiling(Base):
    """Monthly exemption ceiling, versioned the same way — the statutory figure
    is updated annually and past months must keep the number they were judged by."""

    __tablename__ = "ceilings"
    __table_args__ = (UniqueConstraint("user_id", "effective_from", name="uq_ceiling_user_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount_agorot: Mapped[int] = mapped_column(Integer)
    effective_from: Mapped[dt.date] = mapped_column(Date)

    user: Mapped[User] = relationship(back_populates="ceilings")


class Shift(Base):
    __tablename__ = "shifts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    start_utc: Mapped[dt.datetime] = mapped_column(DateTime, index=True)
    # NULL means the shift is still running.
    end_utc: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    # Local calendar date the shift is attributed to (its start date). Kept
    # denormalised so monthly aggregation is a plain indexed range scan.
    work_date: Mapped[dt.date] = mapped_column(Date, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="live")  # live | manual
    total_agorot: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="shifts")
    segments: Mapped[list["ShiftSegment"]] = relationship(
        back_populates="shift", cascade="all, delete-orphan", order_by="ShiftSegment.from_utc"
    )


class ShiftSegment(Base):
    """A priced slice of a shift at one multiplier.

    Materialised rather than recomputed on read: it makes every report auditable,
    and it means a later change to the calendar library or the hourly rate cannot
    silently restate what the user was already told he earned.
    """

    __tablename__ = "shift_segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"), index=True)
    from_utc: Mapped[dt.datetime] = mapped_column(DateTime)
    to_utc: Mapped[dt.datetime] = mapped_column(DateTime)
    hours: Mapped[float] = mapped_column(Float)
    multiplier: Mapped[float] = mapped_column(Float)
    kind: Mapped[str] = mapped_column(String(16))   # regular | rest | night
    # Legacy from the tiered-overtime model; no longer written. Kept so existing
    # databases, where the column is NOT NULL, still accept inserts.
    tier: Mapped[str] = mapped_column(String(8), default="")
    reason: Mapped[str] = mapped_column(String(64), default="")
    amount_agorot: Mapped[int] = mapped_column(Integer)

    shift: Mapped[Shift] = relationship(back_populates="segments")
