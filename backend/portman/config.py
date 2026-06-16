"""Runtime configuration and filesystem locations.

All mutable state lives under ``~/.portman`` (overridable via ``PORTMAN_HOME``)
so the repository never holds runtime data. Tests point ``PORTMAN_HOME`` at a
temporary directory.
"""

from __future__ import annotations

import os
import random
import socket
from pathlib import Path


def _home() -> Path:
    return Path(os.environ.get("PORTMAN_HOME", Path.home() / ".portman"))


DATA_DIR: Path = _home()
DB_PATH: Path = DATA_DIR / "portman.db"
LOGS_DIR: Path = DATA_DIR / "logs"
PID_FILE: Path = DATA_DIR / "daemon.pid"
# The daemon listens on a random, persisted port (see ``daemon_port``).
DAEMON_PORT_FILE: Path = DATA_DIR / "daemon.port"

DEFAULT_HOST: str = os.environ.get("PORTMAN_HOST", "127.0.0.1")

# Inclusive range used when generating random free ports for services.
PORT_RANGE_START: int = 20000
PORT_RANGE_END: int = 60000

# The daemon picks from the IANA dynamic/private range, kept separate from the
# service range above so the control plane never competes for a service port.
DAEMON_PORT_RANGE_START: int = 49152
DAEMON_PORT_RANGE_END: int = 65535

# How often the reconciliation scanner refreshes its view of the system.
SCAN_INTERVAL_SECONDS: float = 5.0


def refresh_from_env() -> None:
    """Recompute paths from the environment (used by tests after monkeypatch)."""
    global DATA_DIR, DB_PATH, LOGS_DIR, PID_FILE, DAEMON_PORT_FILE
    DATA_DIR = _home()
    DB_PATH = DATA_DIR / "portman.db"
    LOGS_DIR = DATA_DIR / "logs"
    PID_FILE = DATA_DIR / "daemon.pid"
    DAEMON_PORT_FILE = DATA_DIR / "daemon.port"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


# --- daemon port -------------------------------------------------------------
#
# A fresh install must not collide with whatever already owns a well-known port,
# so the daemon binds a *random* port chosen once on first use and then reused
# forever (persisted to ``daemon.port``). ``PORTMAN_PORT`` overrides everything
# for users who want a fixed, known port. We use a plain socket bind check here
# rather than ``ports.find_free_port`` to keep this module dependency-free (and
# free of an import cycle with ``ports``).


def _is_bindable(port: int) -> bool:
    """True if ``port`` can be bound on localhost right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((DEFAULT_HOST, port))
            return True
        except OSError:
            return False


def _random_daemon_port(*, attempts: int = 200) -> int:
    """Pick a free port from the daemon range, or raise if the range is full."""
    for _ in range(attempts):
        port = random.randint(DAEMON_PORT_RANGE_START, DAEMON_PORT_RANGE_END)
        if _is_bindable(port):
            return port
    raise RuntimeError(
        f"No free daemon port in range {DAEMON_PORT_RANGE_START}-{DAEMON_PORT_RANGE_END}"
    )


def _port_override() -> int | None:
    raw = os.environ.get("PORTMAN_PORT")
    return int(raw) if raw else None


def _persist_daemon_port(port: int) -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DAEMON_PORT_FILE.write_text(str(port))
    return port


def daemon_port() -> int:
    """Return the daemon's port, generating and persisting one on first use.

    Order of precedence: the ``PORTMAN_PORT`` env override, then the persisted
    value, then a freshly generated random port (which is persisted).
    """
    override = _port_override()
    if override is not None:
        return override
    if DAEMON_PORT_FILE.exists():
        try:
            return int(DAEMON_PORT_FILE.read_text().strip())
        except ValueError:
            pass  # corrupt file → regenerate below
    return _persist_daemon_port(_random_daemon_port())


def set_daemon_port(port: int) -> int:
    """Pin the daemon to an explicit port (persisted)."""
    return _persist_daemon_port(port)


def regenerate_daemon_port() -> int:
    """Force a new random daemon port, replacing any persisted value."""
    return _persist_daemon_port(_random_daemon_port())


def ensure_free_daemon_port() -> int:
    """Resolve the daemon port, regenerating it if the persisted one is taken.

    Used by ``portman up`` so a stale port (something else grabbed it since it
    was chosen) self-heals instead of failing the launch. An explicit
    ``PORTMAN_PORT`` override is respected verbatim — we never second-guess it.
    """
    override = _port_override()
    if override is not None:
        return override
    port = daemon_port()
    if _is_bindable(port):
        return port
    return regenerate_daemon_port()
