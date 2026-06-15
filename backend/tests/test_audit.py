"""Tests for the audit log."""

from __future__ import annotations

from portman import audit, db
from portman.models import AuditType


def test_record_and_list_events_newest_first(temp_db):
    with db.session_scope() as session:
        audit.record(session, AuditType.start.value, service="web", port=3000)
        audit.record(session, AuditType.stop.value, service="web")

    with db.session_scope() as session:
        events = audit.list_events(session)

    assert [e.type for e in events] == ["stop", "start"]
    assert events[1].detail == {"service": "web", "port": 3000}


def test_list_events_respects_limit(temp_db):
    with db.session_scope() as session:
        for i in range(5):
            audit.record(session, AuditType.reserve.value, port=20000 + i)

    with db.session_scope() as session:
        events = audit.list_events(session, limit=2)
    assert len(events) == 2
