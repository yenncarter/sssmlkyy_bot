"""Database models."""

from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base
from domain.dates import now_local
from domain.enums import BookingStatus, SlotStatus


class WorkSettings(Base):
    """Singleton row (id=1) — default salon hours + prepayment."""

    __tablename__ = "work_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    open_time: Mapped[time] = mapped_column(Time, nullable=False)
    close_time: Mapped[time] = mapped_column(Time, nullable=False)
    slot_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    prepayment_amount: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="1 000 ₽",
        server_default="1 000 ₽",
    )


class AppState(Base):
    """Key/value store for operational state that must survive a restart.

    Bothost redeploys the container on every push, so anything kept only in
    process memory (watermarks, last backup time) is lost exactly when it is
    needed most.
    """

    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_local,
        onupdate=now_local,
        server_default=func.now(),
        nullable=False,
    )


class MediaFile(Base):
    """Telegram file_id for a local asset.

    Without this the bot re-uploads every portfolio photo from disk after each
    restart — seconds of latency on the first swipe, for no reason.
    """

    __tablename__ = "media_files"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    file_id: Mapped[str] = mapped_column(String(256), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_local,
        onupdate=now_local,
        server_default=func.now(),
        nullable=False,
    )


class WorkingDay(Base):
    __tablename__ = "working_days"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day: Mapped[date] = mapped_column(Date, unique=True, nullable=False, index=True)
    open_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    close_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    slot_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Python-side default: SQLite's CURRENT_TIMESTAMP is UTC, which would put
    # created_at 3 hours behind every other timestamp in the schema.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_local,
        server_default=func.now(),
        nullable=False,
    )

    slots: Mapped[list[Slot]] = relationship(
        back_populates="working_day",
        cascade="all, delete-orphan",
        order_by="Slot.start_time",
    )


class Slot(Base):
    __tablename__ = "slots"
    __table_args__ = (
        UniqueConstraint("working_day_id", "start_time", name="uq_slot_day_time"),
        Index("ix_slots_status_held_until", "status", "held_until"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    working_day_id: Mapped[int] = mapped_column(
        ForeignKey("working_days.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=SlotStatus.FREE.value,
        server_default=SlotStatus.FREE.value,
    )
    held_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    held_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    working_day: Mapped[WorkingDay] = relationship(back_populates="slots")
    # passive_deletes="all": never let the ORM "detach" bookings by writing NULL
    # into the NOT NULL slot_id. Callers must remove bookings explicitly; the FK
    # (RESTRICT) then fails loudly instead of corrupting a row.
    bookings: Mapped[list[Booking]] = relationship(
        back_populates="slot",
        passive_deletes="all",
    )


class Booking(Base):
    __tablename__ = "bookings"
    # NOTE: indexes here only materialize for a freshly created table.
    # db.session.init_db issues the equivalent CREATE INDEX IF NOT EXISTS so
    # that databases predating them get the constraints too.
    __table_args__ = (
        Index("ix_bookings_user_status", "telegram_user_id", "status"),
        Index("ix_bookings_status", "status"),
        Index(
            "uq_live_booking_slot",
            "slot_id",
            unique=True,
            sqlite_where=text("status IN ('pending_payment', 'active')"),
            postgresql_where=text("status IN ('pending_payment', 'active')"),
        ),
        Index(
            "uq_live_booking_user",
            "telegram_user_id",
            unique=True,
            sqlite_where=text("status IN ('pending_payment', 'active')"),
            postgresql_where=text("status IN ('pending_payment', 'active')"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slot_id: Mapped[int] = mapped_column(
        ForeignKey("slots.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(128), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    service_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    service_title: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=BookingStatus.PENDING_PAYMENT.value,
        server_default=BookingStatus.PENDING_PAYMENT.value,
    )
    receipt_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    receipt_file_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reminded_24h: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    reminded_2h: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_local,
        server_default=func.now(),
        nullable=False,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    slot: Mapped[Slot] = relationship(back_populates="bookings")
