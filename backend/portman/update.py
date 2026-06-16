"""Best-effort "a newer portman is available" notifier and upgrade helper.

portman is a fully local tool, so there is no server that can *force* clients to
update. The respectful, industry-standard alternative is implemented here:

- :func:`check_for_update` asks PyPI for the latest published version at most
  once per day (the result is cached under ``~/.portman``), comparing it against
  the installed version. Every step fails silently — a missing network, a slow
  PyPI, or a malformed response must never break a normal command.
- :func:`notify_if_outdated` prints a one-line nudge (to stderr) when a newer
  version exists. Opt out with ``PORTMAN_NO_UPDATE_CHECK=1``.
- :func:`detect_upgrade_command` picks the right upgrade incantation for how
  portman was installed (pipx / uv tool / pip), backing ``portman upgrade``.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import httpx

from . import config

# The PyPI distribution name (the bare `portman` is taken by an unrelated
# project). The terminal command and the import package both stay `portman`.
_DIST_NAME = "portreeve"
_PYPI_URL = f"https://pypi.org/pypi/{_DIST_NAME}/json"
_CACHE_NAME = "update_check.json"
_DEFAULT_TTL_HOURS = 24.0
_OPT_OUT_ENV = "PORTMAN_NO_UPDATE_CHECK"


def installed_version() -> str | None:
    """The installed portman version, or ``None`` if it cannot be determined."""
    try:
        return version(_DIST_NAME)
    except PackageNotFoundError:
        return None


def _parse(v: str) -> tuple[int, ...]:
    """Parse a version string into a comparable tuple of ints (best effort)."""
    return tuple(int(part) for part in re.findall(r"\d+", v or ""))


def is_newer(latest: str, current: str) -> bool:
    """True if ``latest`` is a strictly newer version than ``current``.

    Fails safe: if either version cannot be parsed, returns ``False`` so we
    never nag on garbage input.
    """
    lt, ct = _parse(latest), _parse(current)
    if not lt or not ct:
        return False
    width = max(len(lt), len(ct))
    lt += (0,) * (width - len(lt))
    ct += (0,) * (width - len(ct))
    return lt > ct


# --- network + cache --------------------------------------------------------


def _cache_path() -> Path:
    return config.DATA_DIR / _CACHE_NAME


def _fetch_latest_version(timeout: float = 1.0) -> str | None:
    """Return the latest version published on PyPI, or ``None`` on any failure."""
    try:
        resp = httpx.get(_PYPI_URL, timeout=timeout)
        resp.raise_for_status()
        return resp.json()["info"]["version"]
    except (httpx.HTTPError, KeyError, ValueError):
        return None


def _read_cache() -> dict | None:
    path = _cache_path()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (ValueError, OSError):
        return None


def _write_cache(latest: str, checked_at: float) -> None:
    try:
        config.ensure_dirs()
        _cache_path().write_text(json.dumps({"latest": latest, "checked_at": checked_at}))
    except OSError:
        pass


def _cached_latest(now: float, ttl_hours: float) -> str | None:
    if ttl_hours <= 0:
        return None  # force a fresh check, regardless of when the cache was written
    data = _read_cache()
    if not data:
        return None
    if now - data.get("checked_at", 0.0) > ttl_hours * 3600:
        return None
    return data.get("latest")


def check_for_update(
    *,
    ttl_hours: float = _DEFAULT_TTL_HOURS,
    timeout: float = 1.0,
    now: float | None = None,
) -> str | None:
    """Return the latest version string if it is newer than installed, else None.

    Uses a per-day cache; only contacts PyPI when the cache is stale. Returns
    ``None`` on any failure (not installed, network down, malformed response).
    """
    current = installed_version()
    if not current:
        return None
    now = time.time() if now is None else now

    latest = _cached_latest(now, ttl_hours)
    if latest is None:
        latest = _fetch_latest_version(timeout)
        if latest is None:
            return None
        _write_cache(latest, now)

    return latest if is_newer(latest, current) else None


# --- user-facing helpers ----------------------------------------------------


def detect_upgrade_command(executable: str | None = None) -> list[str]:
    """Pick the upgrade command for how portman was installed."""
    exe = sys.executable if executable is None else executable
    low = exe.lower()
    if "pipx" in low:
        return ["pipx", "upgrade", _DIST_NAME]
    if f"{os.sep}uv{os.sep}" in low or "/uv/" in low:
        return ["uv", "tool", "upgrade", _DIST_NAME]
    return [exe, "-m", "pip", "install", "--upgrade", _DIST_NAME]


def notify_if_outdated(stream=None) -> None:
    """Print a one-line upgrade nudge if a newer version exists. Never raises."""
    if os.environ.get(_OPT_OUT_ENV):
        return
    stream = sys.stderr if stream is None else stream
    try:
        latest = check_for_update()
        if not latest:
            return
        hint = " ".join(detect_upgrade_command())
        print(
            f"portman {latest} is available (you have {installed_version()}). "
            f"Upgrade: {hint}",
            file=stream,
        )
    except Exception:  # noqa: BLE001 — a notifier must never break a command
        return
