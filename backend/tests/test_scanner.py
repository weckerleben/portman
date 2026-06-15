"""Tests for the reconciliation scanner."""

from __future__ import annotations

from portman import audit, db
from portman.ports import ListeningPort
from portman.scanner import (
    MANAGED,
    UNAUTHORIZED,
    Scanner,
    classify,
    new_unauthorized,
)


def _lp(port: int, pid: int = 100, name: str = "proc") -> ListeningPort:
    return ListeningPort(port=port, pid=pid, name=name, cmdline=f"{name} run", cwd="/p")


def test_classify_marks_managed_and_unauthorized():
    listening = [_lp(3000), _lp(9999)]
    result = classify(listening, managed={3000: 42})

    by_port = {c.port: c for c in result}
    assert by_port[3000].status == MANAGED
    assert by_port[3000].service_id == 42
    assert by_port[9999].status == UNAUTHORIZED
    assert by_port[9999].service_id is None


def test_classify_notes_reservation_squatting():
    # A port is reserved for something, but a process portman did not launch grabbed it.
    result = classify([_lp(5000)], managed={}, reserved={5000: 7})
    assert result[0].status == UNAUTHORIZED
    assert result[0].reservation_id == 7


def test_new_unauthorized_only_returns_unseen():
    classified = classify([_lp(8000), _lp(8001)], managed={})
    assert {c.port for c in new_unauthorized(classified, seen=set())} == {8000, 8001}
    assert {c.port for c in new_unauthorized(classified, seen={8000})} == {8001}


def test_scanner_classify_now_uses_injected_lister():
    scanner = Scanner(lister=lambda: [_lp(3000), _lp(4000)])
    result = scanner.classify_now(managed={3000: 1})
    statuses = {c.port: c.status for c in result}
    assert statuses == {3000: MANAGED, 4000: UNAUTHORIZED}


def test_flag_new_records_audit_only_once_per_port(temp_db):
    scanner = Scanner()
    classified = classify([_lp(8080)], managed={})

    with db.session_scope() as session:
        first = scanner.flag_new(session, classified)
    assert [c.port for c in first] == [8080]

    # Same port still unauthorized on the next scan — must not double-log.
    with db.session_scope() as session:
        second = scanner.flag_new(session, classified)
    assert second == []

    with db.session_scope() as session:
        events = audit.list_events(session)
    flagged = [e for e in events if e.type == "flag_unauthorized"]
    assert len(flagged) == 1
    assert flagged[0].detail["port"] == 8080
