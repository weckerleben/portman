"""SQLAlchemy models — the persisted authorization record.

Status fields store plain strings (the ``*.value`` of the enums below) to keep
the SQLite schema simple and human-readable.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ReservationStatus(str, enum.Enum):
    reserved = "reserved"  # held for a purpose, nothing bound yet
    active = "active"  # a managed service is currently bound here
    free = "free"  # released


class RunStatus(str, enum.Enum):
    running = "running"
    stopped = "stopped"  # exited cleanly / stopped by us
    crashed = "crashed"  # exited with a non-zero code unexpectedly


class AuditType(str, enum.Enum):
    authorize = "authorize"
    start = "start"
    stop = "stop"
    kill = "kill"
    kill_port = "kill_port"
    restart = "restart"
    flag_unauthorized = "flag_unauthorized"
    reserve = "reserve"
    release = "release"


class Service(Base):
    """A registered service: what runs, how, where, and what it does."""

    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    command: Mapped[str] = mapped_column(Text)
    cwd: Mapped[str] = mapped_column(Text, default="")
    env: Mapped[dict] = mapped_column(JSON, default=dict)
    assigned_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    auto_restart: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(20), default="ui")  # ui | manifest
    manifest_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    runs: Mapped[list["Run"]] = relationship(
        back_populates="service", cascade="all, delete-orphan", order_by="Run.started_at.desc()"
    )


class PortReservation(Base):
    """A port held for a specific purpose or service."""

    __tablename__ = "port_reservations"

    id: Mapped[int] = mapped_column(primary_key=True)
    port: Mapped[int] = mapped_column(Integer, index=True)
    purpose: Mapped[str] = mapped_column(Text, default="")
    service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=ReservationStatus.reserved.value)
    reserved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Run(Base):
    """A single execution of a service: its PID, log file and lifecycle."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=RunStatus.running.value)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    log_path: Mapped[str] = mapped_column(Text, default="")

    service: Mapped["Service"] = relationship(back_populates="runs")


class AuditEvent(Base):
    """Append-only record of every authorization and lifecycle action."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    type: Mapped[str] = mapped_column(String(40))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
