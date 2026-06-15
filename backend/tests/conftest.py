"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from portman import config, db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point portman at a throwaway home directory with a fresh schema."""
    monkeypatch.setenv("PORTMAN_HOME", str(tmp_path))
    config.refresh_from_env()
    db.init_db()
    yield
