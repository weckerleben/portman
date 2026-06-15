"""Append-only audit log helpers.

Every authorization or lifecycle action portman takes (or detects) is recorded
here, so there is always an answer to "what ran, when, and on whose say-so".
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import session_scope
from .models import AuditEvent


def record(session: Session, event_type: str, **detail) -> AuditEvent:
    """Add an audit event within an existing session (does not commit)."""
    event = AuditEvent(type=str(event_type), detail=detail or {})
    session.add(event)
    session.flush()
    return event


def log_event(event_type: str, **detail) -> None:
    """Record an audit event in its own transaction."""
    with session_scope() as session:
        record(session, event_type, **detail)


def list_events(session: Session, limit: int = 200) -> list[AuditEvent]:
    stmt = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)
    return list(session.scalars(stmt))
