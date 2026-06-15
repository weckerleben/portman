"""Tests for Anthropic API-key storage."""

from __future__ import annotations

import stat

import pytest

from portman import credentials


@pytest.fixture
def temp_home(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("PORTMAN_HOME", str(tmp_path))
    from portman import config

    config.refresh_from_env()
    yield tmp_path


def test_set_then_get_round_trips(temp_home):
    credentials.set_api_key("sk-ant-test")
    assert credentials.get_api_key() == "sk-ant-test"
    assert credentials.key_source() == "file"


def test_file_is_owner_only(temp_home):
    credentials.set_api_key("sk-ant-test")
    mode = stat.S_IMODE(credentials._path().stat().st_mode)
    assert mode == 0o600


def test_env_takes_precedence(temp_home, monkeypatch):
    credentials.set_api_key("sk-from-file")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    assert credentials.get_api_key() == "sk-from-env"
    assert credentials.key_source() == "env"


def test_clear_removes_key(temp_home):
    credentials.set_api_key("sk-ant-test")
    credentials.clear_api_key()
    assert credentials.get_api_key() is None
    assert credentials.key_source() is None
