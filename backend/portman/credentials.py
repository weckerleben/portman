"""Anthropic API-key storage for the optional AI features.

The key is read from ``ANTHROPIC_API_KEY`` if set (so CI and shells win), and
otherwise from ``~/.portman/credentials.json`` written by ``portman login``.
The file is created owner-readable only (``0o600``).

Note: there is no "log in with your Claude account" flow — that OAuth is
first-party to Anthropic's own apps and not available to third-party tools. An
API key from console.anthropic.com is the supported path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import config

_ENV_VAR = "ANTHROPIC_API_KEY"
_KEY_FIELD = "anthropic_api_key"


def _path() -> Path:
    return config.DATA_DIR / "credentials.json"


def get_api_key() -> str | None:
    """Return the key from the environment, then the stored file, else None."""
    env = os.environ.get(_ENV_VAR)
    if env:
        return env
    path = _path()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text()).get(_KEY_FIELD) or None
    except (json.JSONDecodeError, OSError):
        return None


def key_source() -> str | None:
    """Where ``get_api_key`` would read from: ``"env"``, ``"file"``, or None."""
    if os.environ.get(_ENV_VAR):
        return "env"
    if _path().is_file() and get_api_key():
        return "file"
    return None


def set_api_key(key: str) -> Path:
    """Persist ``key`` to the credentials file with owner-only permissions."""
    config.ensure_dirs()
    path = _path()
    path.write_text(json.dumps({_KEY_FIELD: key.strip()}))
    path.chmod(0o600)
    return path


def clear_api_key() -> None:
    """Remove the stored key (no-op if absent). Does not touch the env var."""
    _path().unlink(missing_ok=True)
