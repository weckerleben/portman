"""Tests for the update notifier and the ``portman upgrade`` command helper."""

from __future__ import annotations

import io
import json
from importlib.metadata import PackageNotFoundError

import pytest

from portman import config, update


@pytest.fixture()
def portman_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTMAN_HOME", str(tmp_path))
    monkeypatch.delenv("PORTMAN_NO_UPDATE_CHECK", raising=False)
    config.refresh_from_env()
    yield tmp_path
    config.refresh_from_env()


# --- version comparison -----------------------------------------------------


def test_is_newer_detects_higher_version():
    assert update.is_newer("0.2.0", "0.1.0") is True
    assert update.is_newer("1.0.0", "0.9.9") is True


def test_is_newer_false_for_same_or_older():
    assert update.is_newer("0.1.0", "0.1.0") is False
    assert update.is_newer("0.1.0", "0.2.0") is False


def test_is_newer_treats_missing_patch_as_zero():
    assert update.is_newer("0.2", "0.2.0") is False


def test_is_newer_fails_safe_on_garbage():
    assert update.is_newer("", "1.0.0") is False
    assert update.is_newer("not-a-version", "1.0.0") is False


# --- check_for_update -------------------------------------------------------


def test_check_returns_latest_and_caches_when_newer(portman_home, monkeypatch):
    monkeypatch.setattr(update, "installed_version", lambda: "0.1.0")
    monkeypatch.setattr(update, "_fetch_latest_version", lambda timeout=1.0: "9.9.9")

    assert update.check_for_update(now=1000.0) == "9.9.9"

    cached = json.loads((portman_home / "update_check.json").read_text())
    assert cached["latest"] == "9.9.9"
    assert cached["checked_at"] == 1000.0


def test_check_returns_none_when_up_to_date(portman_home, monkeypatch):
    monkeypatch.setattr(update, "installed_version", lambda: "9.9.9")
    monkeypatch.setattr(update, "_fetch_latest_version", lambda timeout=1.0: "9.9.9")

    assert update.check_for_update(now=1000.0) is None


def test_check_uses_cache_within_ttl_without_fetching(portman_home, monkeypatch):
    (portman_home / "update_check.json").write_text(
        json.dumps({"latest": "9.9.9", "checked_at": 1000.0})
    )
    monkeypatch.setattr(update, "installed_version", lambda: "0.1.0")

    def _boom(timeout=1.0):
        raise AssertionError("network should not be hit within TTL")

    monkeypatch.setattr(update, "_fetch_latest_version", _boom)

    assert update.check_for_update(now=1000.0 + 3600) == "9.9.9"


def test_check_refetches_when_cache_is_stale(portman_home, monkeypatch):
    (portman_home / "update_check.json").write_text(
        json.dumps({"latest": "0.1.0", "checked_at": 0.0})
    )
    monkeypatch.setattr(update, "installed_version", lambda: "0.1.0")
    monkeypatch.setattr(update, "_fetch_latest_version", lambda timeout=1.0: "2.0.0")

    later = 48 * 3600.0
    assert update.check_for_update(now=later) == "2.0.0"


def test_check_with_zero_ttl_refetches_despite_fresh_cache(portman_home, monkeypatch):
    # A fresh cache (checked just now) would normally be reused…
    (portman_home / "update_check.json").write_text(
        json.dumps({"latest": "0.1.0", "checked_at": 1000.0})
    )
    monkeypatch.setattr(update, "installed_version", lambda: "0.1.0")
    monkeypatch.setattr(update, "_fetch_latest_version", lambda timeout=1.0: "2.0.0")

    # …but ttl_hours=0 forces a remote check (this is what `portman upgrade` uses).
    assert update.check_for_update(ttl_hours=0, now=1000.0) == "2.0.0"


def test_check_is_silent_on_network_failure(portman_home, monkeypatch):
    monkeypatch.setattr(update, "installed_version", lambda: "0.1.0")
    monkeypatch.setattr(update, "_fetch_latest_version", lambda timeout=1.0: None)

    assert update.check_for_update(now=1000.0) is None


def test_check_returns_none_when_not_installed(portman_home, monkeypatch):
    monkeypatch.setattr(update, "installed_version", lambda: None)
    assert update.check_for_update(now=1000.0) is None


# --- notify_if_outdated -----------------------------------------------------


def test_notify_prints_when_update_available(monkeypatch):
    monkeypatch.delenv("PORTMAN_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(update, "check_for_update", lambda: "9.9.9")
    monkeypatch.setattr(update, "installed_version", lambda: "0.1.0")
    out = io.StringIO()

    update.notify_if_outdated(stream=out)

    text = out.getvalue()
    assert "9.9.9" in text
    assert "upgrade" in text.lower()


def test_notify_silent_when_current(monkeypatch):
    monkeypatch.delenv("PORTMAN_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(update, "check_for_update", lambda: None)
    out = io.StringIO()

    update.notify_if_outdated(stream=out)

    assert out.getvalue() == ""


def test_notify_respects_opt_out_env(monkeypatch):
    monkeypatch.setenv("PORTMAN_NO_UPDATE_CHECK", "1")

    def _boom():
        raise AssertionError("check_for_update should not run when opted out")

    monkeypatch.setattr(update, "check_for_update", _boom)
    out = io.StringIO()

    update.notify_if_outdated(stream=out)

    assert out.getvalue() == ""


def test_notify_never_raises(monkeypatch):
    monkeypatch.delenv("PORTMAN_NO_UPDATE_CHECK", raising=False)

    def _boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(update, "check_for_update", _boom)
    update.notify_if_outdated(stream=io.StringIO())  # must not raise


# --- network + cache internals ----------------------------------------------


def test_installed_version_none_when_not_installed(monkeypatch):
    def _missing(_name):
        raise PackageNotFoundError

    monkeypatch.setattr(update, "version", _missing)
    assert update.installed_version() is None


def test_fetch_latest_parses_pypi_payload(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"info": {"version": "3.2.1"}}

    monkeypatch.setattr(update.httpx, "get", lambda url, timeout: FakeResp())
    assert update._fetch_latest_version() == "3.2.1"


def test_fetch_latest_silent_on_http_error(monkeypatch):
    def _boom(url, timeout):
        raise update.httpx.HTTPError("down")

    monkeypatch.setattr(update.httpx, "get", _boom)
    assert update._fetch_latest_version() is None


def test_read_cache_returns_none_on_corrupt_file(portman_home):
    config.ensure_dirs()
    (config.DATA_DIR / "update_check.json").write_text("{not json")
    assert update._read_cache() is None


def test_write_cache_is_silent_on_oserror(portman_home):
    config.ensure_dirs()
    # A directory where the cache file should be makes write_text raise OSError.
    (config.DATA_DIR / "update_check.json").mkdir()
    update._write_cache("1.0.0", 1234.0)  # must not raise


# --- detect_upgrade_command -------------------------------------------------


def test_detect_upgrade_command_pipx():
    exe = "/Users/me/.local/pipx/venvs/portreeve/bin/python"
    assert update.detect_upgrade_command(exe) == ["pipx", "upgrade", "portreeve"]


def test_detect_upgrade_command_uv():
    exe = "/Users/me/.local/share/uv/tools/portreeve/bin/python"
    assert update.detect_upgrade_command(exe) == ["uv", "tool", "upgrade", "portreeve"]


def test_detect_upgrade_command_falls_back_to_pip():
    exe = "/usr/bin/python3"
    assert update.detect_upgrade_command(exe) == [
        exe,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "portreeve",
    ]
