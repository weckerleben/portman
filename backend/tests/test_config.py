"""Tests for the daemon's random, persisted port resolution."""

from __future__ import annotations

import pytest

from portman import config


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.delenv("PORTMAN_PORT", raising=False)
    monkeypatch.setenv("PORTMAN_HOME", str(tmp_path))
    config.refresh_from_env()
    yield tmp_path


def test_daemon_port_is_generated_and_persisted(home, monkeypatch):
    monkeypatch.setattr(config, "_random_daemon_port", lambda **_: 51234)

    first = config.daemon_port()
    assert first == 51234
    assert config.DAEMON_PORT_FILE.read_text().strip() == "51234"

    # A second call reads the persisted value instead of generating anew.
    monkeypatch.setattr(config, "_random_daemon_port", lambda **_: 9999)
    assert config.daemon_port() == 51234


def test_generated_port_is_in_the_daemon_range(home):
    port = config.daemon_port()
    assert config.DAEMON_PORT_RANGE_START <= port <= config.DAEMON_PORT_RANGE_END


def test_env_override_wins_and_does_not_persist(home, monkeypatch):
    monkeypatch.setenv("PORTMAN_PORT", "8080")
    assert config.daemon_port() == 8080
    assert not config.DAEMON_PORT_FILE.exists()  # override is not written to disk


def test_set_daemon_port_pins_an_explicit_value(home):
    assert config.set_daemon_port(40000) == 40000
    assert config.daemon_port() == 40000


def test_regenerate_replaces_the_persisted_port(home, monkeypatch):
    config.set_daemon_port(40000)
    monkeypatch.setattr(config, "_random_daemon_port", lambda **_: 55555)
    assert config.regenerate_daemon_port() == 55555
    assert config.daemon_port() == 55555


def test_corrupt_port_file_is_regenerated(home, monkeypatch):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.DAEMON_PORT_FILE.write_text("not-a-port")
    monkeypatch.setattr(config, "_random_daemon_port", lambda **_: 50001)
    assert config.daemon_port() == 50001


def test_ensure_free_keeps_a_bindable_port(home, monkeypatch):
    config.set_daemon_port(40000)
    monkeypatch.setattr(config, "_is_bindable", lambda port: True)
    assert config.ensure_free_daemon_port() == 40000


def test_ensure_free_regenerates_when_taken(home, monkeypatch):
    config.set_daemon_port(40000)
    monkeypatch.setattr(config, "_is_bindable", lambda port: port != 40000)
    monkeypatch.setattr(config, "_random_daemon_port", lambda **_: 50002)
    assert config.ensure_free_daemon_port() == 50002
    assert config.daemon_port() == 50002


def test_ensure_free_respects_env_override(home, monkeypatch):
    monkeypatch.setenv("PORTMAN_PORT", "8080")
    # Even if 8080 looks taken, an explicit override is never second-guessed.
    monkeypatch.setattr(config, "_is_bindable", lambda port: False)
    assert config.ensure_free_daemon_port() == 8080


def test_is_bindable_false_when_port_is_taken(home):
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        taken = sock.getsockname()[1]
        assert config._is_bindable(taken) is False  # OSError branch
