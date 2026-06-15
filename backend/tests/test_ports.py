"""Tests for port/process introspection and free-port generation.

psutil is mocked so these run deterministically without touching real sockets.
We mock ``process_iter`` because port discovery enumerates per process (the
macOS-safe path that avoids the root-only system-wide call).
"""

from __future__ import annotations

import random
from collections import namedtuple
from unittest.mock import MagicMock, patch

from portman import ports

# Mirror the shape psutil connection objects expose.
_Addr = namedtuple("addr", ["ip", "port"])
_Conn = namedtuple("pconn", ["fd", "family", "type", "laddr", "raddr", "status"])


def _conn(port: int, status: str = "LISTEN", ip: str = "127.0.0.1") -> _Conn:
    return _Conn(1, 2, 1, _Addr(ip, port), (), status)


def _proc(
    pid: int,
    conns,
    *,
    name: str = "node",
    cmdline=("node", "server.js"),
    cwd: str = "/proj",
    access_denied: bool = False,
    name_denied: bool = False,
) -> MagicMock:
    proc = MagicMock()
    proc.pid = pid
    if access_denied:
        proc.net_connections.side_effect = ports.psutil.AccessDenied(pid)
    else:
        proc.net_connections.return_value = list(conns)
    proc.name.side_effect = ports.psutil.AccessDenied(pid) if name_denied else None
    if not name_denied:
        proc.name.return_value = name
    proc.cmdline.return_value = list(cmdline)
    proc.cwd.return_value = cwd
    proc.username.return_value = "will"
    return proc


def _patch_procs(procs):
    return patch.object(ports.psutil, "process_iter", return_value=procs)


# --- list_listening ---------------------------------------------------------


def test_list_listening_describes_each_listening_socket():
    procs = [
        _proc(111, [_conn(3000)], name="node", cmdline=("node", "server.js"), cwd="/proj/web"),
        _proc(222, [_conn(5432)], name="postgres", cmdline=("postgres", "-D", "/data")),
    ]
    with _patch_procs(procs):
        result = ports.list_listening()

    assert [p.port for p in result] == [3000, 5432]
    web = result[0]
    assert web.pid == 111
    assert web.name == "node"
    assert web.cmdline == "node server.js"
    assert web.cwd == "/proj/web"


def test_list_listening_ignores_non_listening_connections():
    procs = [
        _proc(111, [_conn(3000)]),
        _proc(333, [_conn(9999, status="ESTABLISHED")]),
    ]
    with _patch_procs(procs):
        result = ports.list_listening()
    assert [p.port for p in result] == [3000]


def test_list_listening_deduplicates_ipv4_and_ipv6_for_same_pid():
    procs = [_proc(444, [_conn(8080, ip="0.0.0.0"), _conn(8080, ip="::")])]
    with _patch_procs(procs):
        result = ports.list_listening()
    assert len(result) == 1
    assert result[0].port == 8080


def test_list_listening_skips_processes_that_deny_access():
    procs = [_proc(111, [_conn(3000)]), _proc(222, [], access_denied=True)]
    with _patch_procs(procs):
        result = ports.list_listening()
    assert [p.port for p in result] == [3000]


def test_list_listening_reports_port_even_when_metadata_is_denied():
    procs = [_proc(111, [_conn(3000)], name_denied=True, cmdline=())]
    with _patch_procs(procs):
        result = ports.list_listening()
    assert result[0].pid == 111
    assert result[0].name == ""  # metadata unavailable, but the port is still reported


# --- pids_on_port -----------------------------------------------------------


def test_pids_on_port_returns_listening_pids():
    procs = [
        _proc(111, [_conn(3000)]),
        _proc(112, [_conn(3000)]),
        _proc(222, [_conn(5432)]),
    ]
    with _patch_procs(procs):
        assert sorted(ports.pids_on_port(3000)) == [111, 112]
    with _patch_procs(procs):
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
