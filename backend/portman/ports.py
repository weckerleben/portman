"""Port & process introspection plus free-port generation.

This module is the system-truth layer: it inspects what is *actually* listening
right now via psutil, independent of what portman thinks it manages. The scanner
reconciles the two.

We iterate per process (``proc.net_connections``) rather than calling the
system-wide ``psutil.net_connections``: on macOS the latter requires root, while
per-process enumeration works without elevation for the current user's own
processes — which is exactly the set of dev servers portman cares about.
"""

from __future__ import annotations

import random as _random_module
import socket
from dataclasses import asdict, dataclass
from typing import Callable, Iterable, Iterator

import psutil

from . import config

LISTEN = "LISTEN"
_PROC_ERRORS = (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess)


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


def _safe(getter: Callable[[], object], default: str = "") -> str:
    try:
        return getter()  # type: ignore[return-value]
    except _PROC_ERRORS:
        return default


def _describe(proc: "psutil.Process", port: int, laddr_ip: str) -> ListeningPort:
    name = _safe(proc.name)
    cmdline_parts = []
    try:
        cmdline_parts = proc.cmdline()
    except _PROC_ERRORS:
        pass
    return ListeningPort(
        port=port,
        pid=proc.pid,
        name=name,
        cmdline=" ".join(cmdline_parts) or name,
        cwd=_safe(proc.cwd),
        username=_safe(proc.username),
        laddr=laddr_ip,
    )


def _iter_listening() -> Iterator[tuple["psutil.Process", object]]:
    for proc in psutil.process_iter():
        try:
            conns = proc.net_connections(kind="inet")
        except _PROC_ERRORS:
            continue
        for conn in conns:
            if conn.status == LISTEN and conn.laddr:
                yield proc, conn


def list_listening() -> list[ListeningPort]:
    """Return every TCP port in the LISTEN state (for accessible processes).

    IPv4/IPv6 duplicates for the same (port, pid) are collapsed into one entry.
    """
    out: list[ListeningPort] = []
    seen: set[tuple[int, int | None]] = set()
    for proc, conn in _iter_listening():
        port = conn.laddr.port
        key = (port, proc.pid)
        if key in seen:
            continue
        seen.add(key)
        out.append(_describe(proc, port, conn.laddr.ip))
    out.sort(key=lambda p: p.port)
    return out


def pids_on_port(port: int) -> list[int]:
    """Return the PIDs of accessible processes listening on ``port``."""
    pids: list[int] = []
    for proc, conn in _iter_listening():
        if conn.laddr.port == port and proc.pid not in pids:
            pids.append(proc.pid)
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
