"""Runtime configuration and filesystem locations.

All mutable state lives under ``~/.portman`` (overridable via ``PORTMAN_HOME``)
so the repository never holds runtime data. Tests point ``PORTMAN_HOME`` at a
temporary directory.
"""

from __future__ import annotations

import os
from pathlib import Path


def _home() -> Path:
    return Path(os.environ.get("PORTMAN_HOME", Path.home() / ".portman"))


DATA_DIR: Path = _home()
DB_PATH: Path = DATA_DIR / "portman.db"
LOGS_DIR: Path = DATA_DIR / "logs"
PID_FILE: Path = DATA_DIR / "daemon.pid"

DEFAULT_HOST: str = os.environ.get("PORTMAN_HOST", "127.0.0.1")
DEFAULT_PORT: int = int(os.environ.get("PORTMAN_PORT", "7878"))

# Inclusive range used when generating random free ports.
PORT_RANGE_START: int = 20000
PORT_RANGE_END: int = 60000

# How often the reconciliation scanner refreshes its view of the system.
SCAN_INTERVAL_SECONDS: float = 5.0


def refresh_from_env() -> None:
    """Recompute paths from the environment (used by tests after monkeypatch)."""
    global DATA_DIR, DB_PATH, LOGS_DIR, PID_FILE
    DATA_DIR = _home()
    DB_PATH = DATA_DIR / "portman.db"
    LOGS_DIR = DATA_DIR / "logs"
    PID_FILE = DATA_DIR / "daemon.pid"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
