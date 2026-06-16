"""Coverage for small internal modules and edge branches.

Groups focused tests for db, credentials, audit, app error handling, port
binding, config port generation, and the runtime scan loop / helpers.
"""

from __future__ import annotations

import asyncio
import socket
from collections import namedtuple
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from portman import audit, config, credentials, db, ports, runtime
from portman.app import create_app
from portman.models import AuditEvent, Service


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.delenv("PORTMAN_PORT", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("PORTMAN_HOME", str(tmp_path))
    config.refresh_from_env()
    yield tmp_path


# --- db ---------------------------------------------------------------------


def test_get_engine_builds_lazily_after_dispose(home):
    db.init_db()
    db.dispose()
    assert db.get_engine() is not None  # rebuilt on demand
    db.dispose()


def test_session_scope_builds_when_uninitialised(home):
    db.init_db()
    db.dispose()
    with db.session_scope() as session:  # _SessionLocal None → triggers get_engine()
        session.add(Service(name="x", slug="x", command="echo"))
    db.dispose()


# --- credentials ------------------------------------------------------------


def test_get_api_key_handles_corrupt_file(home):
    config.ensure_dirs()
    (config.DATA_DIR / "credentials.json").write_text("not json")
    assert credentials.get_api_key() is None


def test_set_get_clear_roundtrip(home):
    credentials.set_api_key("sk-ant-xyz")
    assert credentials.get_api_key() == "sk-ant-xyz"
    assert credentials.key_source() == "file"
    credentials.clear_api_key()
    assert credentials.get_api_key() is None


# --- audit ------------------------------------------------------------------


def test_log_event_commits_in_its_own_transaction(home):
    db.init_db()
    audit.log_event("custom", foo="bar")
    with db.session_scope() as session:
        events = list(session.scalars(select(AuditEvent)))
    assert any(e.type == "custom" for e in events)
    db.dispose()


# --- app: ServiceError exception handler ------------------------------------


def test_app_handles_uncaught_service_error(home, monkeypatch):
    monkeypatch.setattr(ports, "list_listening", lambda: [])
    with TestClient(create_app()) as client:
        monkeypatch.setattr(
            runtime, "ports_view", lambda s: (_ for _ in ()).throw(runtime.ServiceError("boom"))
        )
        assert client.get("/api/ports").status_code == 400
        monkeypatch.setattr(
            runtime,
            "ports_view",
            lambda s: (_ for _ in ()).throw(runtime.ServiceError("thing not found")),
        )
        assert client.get("/api/ports").status_code == 404


# --- ports ------------------------------------------------------------------


def test_is_port_free_false_when_bound(home):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        port = sock.getsockname()[1]
        assert ports.is_port_free(port) is False
    assert ports.is_port_free(port) is True  # bindable again once released


def test_describe_tolerates_denied_cmdline(home):
    Addr = namedtuple("addr", ["ip", "port"])
    Conn = namedtuple("pconn", ["fd", "family", "type", "laddr", "raddr", "status"])
    proc = mock.MagicMock()
    proc.pid = 42
    proc.net_connections.return_value = [Conn(1, 2, 1, Addr("127.0.0.1", 6010), (), "LISTEN")]
    proc.name.return_value = "svc"
    proc.cmdline.side_effect = ports.psutil.AccessDenied(42)
    proc.cwd.return_value = "/tmp"
    proc.username.return_value = "u"
    with mock.patch.object(ports.psutil, "process_iter", return_value=[proc]):
        out = ports.list_listening()
    assert out[0].port == 6010
    assert out[0].cmdline == "svc"  # falls back to the process name


# --- config: real random port generation ------------------------------------


def test_random_daemon_port_returns_bindable(home):
    port = config._random_daemon_port()
    assert config.DAEMON_PORT_RANGE_START <= port <= config.DAEMON_PORT_RANGE_END


def test_random_daemon_port_raises_when_exhausted(home):
    with pytest.raises(RuntimeError):
        config._random_daemon_port(attempts=0)


# --- runtime: helpers + scan loop -------------------------------------------


def test_unique_slug_disambiguates_collisions(home):
    db.init_db()
    with db.session_scope() as session:
        session.add(Service(name="web", slug=runtime.unique_slug(session, "web"), command="x"))
        session.flush()
        second = runtime.unique_slug(session, "web")
    assert second == "web-2"
    db.dispose()


def test_reserve_port_backfills_purpose_idempotently(home):
    db.init_db()

    class Data:
        def __init__(self, port, purpose):
            self.port = port
            self.purpose = purpose
            self.auto = False

    with db.session_scope() as session:
        runtime.reserve_port(session, Data(7777, ""))  # reserved with no purpose
        res = runtime.reserve_port(session, Data(7777, "db"))  # same port, now named
    assert res.purpose == "db"
    db.dispose()


def test_listening_port_to_dict_roundtrip():
    lp = ports.ListeningPort(port=3000, pid=5, name="node")
    assert ports.ListeningPort(**lp.to_dict()) == lp


def test_reserve_port_requires_port_or_auto(home):
    db.init_db()

    class Data:
        port = None
        auto = False
        purpose = ""

    with db.session_scope() as session:
        with pytest.raises(runtime.ServiceError):
            runtime.reserve_port(session, Data())
    db.dispose()


def test_reserve_port_auto_picks_free(home, monkeypatch):
    db.init_db()
    monkeypatch.setattr(ports, "list_listening", lambda: [])

    class Data:
        port = None
        auto = True
        purpose = "cache"

    with db.session_scope() as session:
        res = runtime.reserve_port(session, Data())
    assert config.PORT_RANGE_START <= res.port <= config.PORT_RANGE_END
    db.dispose()


def test_version_fallback_when_not_installed(monkeypatch):
    import importlib
    from importlib import metadata

    import portman

    def _missing(_name):
        raise metadata.PackageNotFoundError

    monkeypatch.setattr(metadata, "version", _missing)
    importlib.reload(portman)
    try:
        assert portman.__version__ == "0.0.0+unknown"
    finally:
        monkeypatch.undo()
        importlib.reload(portman)  # restore the real installed version


@pytest.mark.asyncio
async def test_scan_loop_swallows_errors_then_continues(home, monkeypatch):
    db.init_db()
    calls = {"classify": 0, "sleep": 0}

    def classify(managed, reserved):
        calls["classify"] += 1
        if calls["classify"] == 1:
            raise RuntimeError("transient")  # exercised by the except Exception guard
        return []

    async def fake_sleep(delay):
        calls["sleep"] += 1
        if calls["sleep"] >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(runtime.scanner, "classify_now", classify)
    monkeypatch.setattr(runtime.scanner, "flag_new", lambda session, classified: None)
    monkeypatch.setattr(runtime.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await runtime.scan_loop(interval=0.01)
    assert calls["classify"] == 2  # first raised, second succeeded
    db.dispose()
