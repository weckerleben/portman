"""Tests for port/process introspection and free-port generation.

psutil is mocked so these run deterministically without touching real sockets.
"""

from __future__ import annotations

import random
from collections import namedtuple
from unittest.mock import MagicMock, patch

from portman import ports

# Mirror the shape psutil.net_connections returns.
_Addr = namedtuple("addr", ["ip", "port"])
_Conn = namedtuple("sconn", ["fd", "family", "type", "laddr", "raddr", "status", "pid"])


def _conn(port: int, pid: int | None, status: str = "LISTEN", ip: str = "127.0.0.1") -> _Conn:
    return _Conn(1, 2, 1, _Addr(ip, port), (), status, pid)


def _fake_process(name: str, cmdline: list[str], cwd: str, username: str) -> MagicMock:
    proc = MagicMock()
    proc.name.return_value = name
    proc.cmdline.return_value = cmdline
    proc.cwd.return_value = cwd
    proc.username.return_value = username
    return proc


# --- list_listening ---------------------------------------------------------


def test_list_listening_describes_each_listening_socket():
    conns = [_conn(3000, 111), _conn(5432, 222)]
    procs = {
        111: _fake_process("node", ["node", "server.js"], "/proj/web", "will"),
        222: _fake_process("postgres", ["postgres", "-D", "/data"], "/var/pg", "will"),
    }
    with patch.object(ports.psutil, "net_connections", return_value=conns), patch.object(
        ports.psutil, "Process", side_effect=lambda pid: procs[pid]
    ):
        result = ports.list_listening()

    assert [p.port for p in result] == [3000, 5432]
    web = result[0]
    assert web.pid == 111
    assert web.name == "node"
    assert web.cmdline == "node server.js"
    assert web.cwd == "/proj/web"


def test_list_listening_ignores_non_listening_connections():
    conns = [_conn(3000, 111), _conn(9999, 333, status="ESTABLISHED")]
    with patch.object(ports.psutil, "net_connections", return_value=conns), patch.object(
        ports.psutil, "Process", return_value=_fake_process("x", ["x"], "/", "will")
    ):
        result = ports.list_listening()
    assert [p.port for p in result] == [3000]


def test_list_listening_deduplicates_ipv4_and_ipv6_for_same_pid():
    conns = [_conn(8080, 444, ip="0.0.0.0"), _conn(8080, 444, ip="::")]
    with patch.object(ports.psutil, "net_connections", return_value=conns), patch.object(
        ports.psutil, "Process", return_value=_fake_process("svc", ["svc"], "/", "will")
    ):
        result = ports.list_listening()
    assert len(result) == 1
    assert result[0].port == 8080


def test_list_listening_survives_vanished_process():
    conns = [_conn(3000, 111)]
    with patch.object(ports.psutil, "net_connections", return_value=conns), patch.object(
        ports.psutil, "Process", side_effect=ports.psutil.NoSuchProcess(111)
    ):
        result = ports.list_listening()
    assert len(result) == 1
    assert result[0].pid == 111
    assert result[0].name == ""  # unresolved, but still reported


# --- pids_on_port -----------------------------------------------------------


def test_pids_on_port_returns_listening_pids():
    conns = [_conn(3000, 111), _conn(3000, 112), _conn(5432, 222)]
    with patch.object(ports.psutil, "net_connections", return_value=conns), patch.object(
        ports.psutil, "Process", return_value=_fake_process("x", ["x"], "/", "will")
    ):
        assert sorted(ports.pids_on_port(3000)) == [111, 112]
        assert ports.pids_on_port(9999) == []


# --- find_free_port ---------------------------------------------------------


def test_find_free_port_returns_port_in_range():
    port = ports.find_free_port(20000, 20010, is_free=lambda p: True, rng=random.Random(1))
    assert 20000 <= port <= 20010


def test_find_free_port_skips_excluded_and_busy():
    busy = {20000, 20001, 20002}
    excluded = {20003, 20004}
    port = ports.find_free_port(
        20000,
        20005,
        exclude=excluded,
        is_free=lambda p: p not in busy,
        rng=random.Random(7),
    )
    assert port == 20005


def test_find_free_port_raises_when_none_available():
    import pytest

    with pytest.raises(RuntimeError):
        ports.find_free_port(20000, 20002, is_free=lambda p: False, rng=random.Random(1))
