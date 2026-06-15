"""Port & process introspection plus free-port generation.

This module is the system-truth layer: it inspects what is *actually* listening
right now via psutil, independent of what portman thinks it manages. The scanner
reconciles the two.
"""

from __future__ import annotations

import random as _random_module
import socket
from dataclasses import asdict, dataclass
from typing import Callable, Iterable

import psutil

from . import config

LISTEN = "LISTEN"


@dataclass(frozen=True)
class ListeningPort:
    """A single port a process is listening on, with describing metadata."""

    port: int
    pid: int | None
    name: str = ""
    cmdline: str = ""
    cwd: str = ""
    username: str = ""
    laddr: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _describe(port: int, pid: int | None, laddr_ip: str) -> ListeningPort:
    name = cmdline = cwd = username = ""
    if pid:
        try:
            proc = psutil.Process(pid)
            name = proc.name()
            cmdline = " ".join(proc.cmdline()) or name
            cwd = proc.cwd()
            username = proc.username()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            # Process vanished or is not introspectable — still report the port.
            pass
    return ListeningPort(
        port=port,
        pid=pid,
        name=name,
        cmdline=cmdline,
        cwd=cwd,
        username=username,
        laddr=laddr_ip,
    )


def list_listening() -> list[ListeningPort]:
    """Return every TCP port currently in the LISTEN state, with process info.

    IPv4/IPv6 duplicates for the same (port, pid) are collapsed into one entry.
    """
    out: list[ListeningPort] = []
    seen: set[tuple[int, int | None]] = set()
    for conn in psutil.net_connections(kind="inet"):
        if conn.status != LISTEN or not conn.laddr:
            continue
        port = conn.laddr.port
        key = (port, conn.pid)
        if key in seen:
            continue
        seen.add(key)
        out.append(_describe(port, conn.pid, conn.laddr.ip))
    out.sort(key=lambda p: p.port)
    return out


def pids_on_port(port: int) -> list[int]:
    """Return the PIDs of processes listening on ``port``."""
    pids: list[int] = []
    for conn in psutil.net_connections(kind="inet"):
        if conn.status == LISTEN and conn.laddr and conn.laddr.port == port and conn.pid:
            if conn.pid not in pids:
                pids.append(conn.pid)
    return pids


def is_port_free(port: int) -> bool:
    """True if ``port`` can be bound on localhost right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def find_free_port(
    start: int = config.PORT_RANGE_START,
    end: int = config.PORT_RANGE_END,
    *,
    exclude: Iterable[int] | None = None,
    is_free: Callable[[int], bool] | None = None,
    rng: _random_module.Random | None = None,
) -> int:
    """Pick a random free port in ``[start, end]`` not in ``exclude``.

    Scans the range in randomized order so the result is unpredictable but the
    search is exhaustive — it only raises when genuinely nothing is available.
    """
    excluded = set(exclude or ())
    check = is_free or is_port_free
    picker = rng or _random_module
    candidates = [p for p in range(start, end + 1) if p not in excluded]
    picker.shuffle(candidates)
    for port in candidates:
        if check(port):
            return port
    raise RuntimeError(f"No free port available in range {start}-{end}")
