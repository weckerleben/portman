"""CLI command tests.

The CLI is a thin HTTP client over the daemon. We point its ``_client`` at an
in-process FastAPI ``TestClient`` (sharing one throwaway ``PORTMAN_HOME``), stub
the daemon-liveness check, and silence the update nudge — so every command runs
without a real daemon, subprocess, or network.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from portman import __version__, cli, config, db, ports, runtime
from portman.app import create_app

runner = CliRunner()


@pytest.fixture
def seed(tmp_path, monkeypatch):
    """A non-lifespan TestClient for seeding data; CLI talks to the same app/db."""
    monkeypatch.setenv("PORTMAN_HOME", str(tmp_path))
    config.refresh_from_env()
    monkeypatch.setattr(ports, "list_listening", lambda: [])
    runtime.scanner._lister = lambda: []
    runtime.scanner._seen_unauthorized = set()
    runtime.supervisor._procs.clear()
    db.init_db()
    app = create_app()
    monkeypatch.setattr(cli, "_client", lambda: TestClient(app))
    monkeypatch.setattr(cli, "_daemon_running", lambda: True)
    monkeypatch.setattr(cli.update_mod, "notify_if_outdated", lambda: None)
    yield TestClient(app)
    db.dispose()


def _register(seed, **kwargs) -> dict:
    payload = {"name": "web", "command": "python -m http.server", "port": 8123}
    payload.update(kwargs)
    resp = seed.post("/api/services", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- --version --------------------------------------------------------------


def test_version_flag_prints_installed_version():
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_version_short_flag_matches_long():
    long = runner.invoke(cli.app, ["--version"]).stdout
    short = runner.invoke(cli.app, ["-v"]).stdout
    assert long == short


# --- logs -------------------------------------------------------------------


def test_logs_reports_no_runs_for_fresh_service(seed):
    _register(seed)
    result = runner.invoke(cli.app, ["logs", "web"])
    assert result.exit_code == 0
    assert "No runs" in result.stdout


def test_logs_unknown_service_errors(seed):
    result = runner.invoke(cli.app, ["logs", "ghost"])
    assert result.exit_code == 1
    assert "No service matching" in result.stdout


# --- unregister / rm --------------------------------------------------------


def test_unregister_removes_service(seed):
    _register(seed)
    result = runner.invoke(cli.app, ["unregister", "web", "--yes"])
    assert result.exit_code == 0
    assert seed.get("/api/services").json() == []


def test_rm_alias_removes_service(seed):
    _register(seed)
    result = runner.invoke(cli.app, ["rm", "web", "--yes"])
    assert result.exit_code == 0
    assert seed.get("/api/services").json() == []


def test_unregister_unknown_service_errors(seed):
    result = runner.invoke(cli.app, ["unregister", "ghost", "--yes"])
    assert result.exit_code == 1


# --- reservations / release -------------------------------------------------


def test_reservations_lists_reserved_port(seed):
    seed.post("/api/reservations", json={"port": 9100, "purpose": "db", "auto": False})
    result = runner.invoke(cli.app, ["reservations"])
    assert result.exit_code == 0
    assert "9100" in result.stdout


def test_release_frees_a_reservation(seed):
    seed.post("/api/reservations", json={"port": 9100, "purpose": "db", "auto": False})
    result = runner.invoke(cli.app, ["release", "9100"])
    assert result.exit_code == 0
    assert seed.get("/api/reservations").json() == []


def test_release_unknown_port_errors(seed):
    result = runner.invoke(cli.app, ["release", "9999"])
    assert result.exit_code == 1


# --- audit ------------------------------------------------------------------


def test_audit_runs(seed):
    _register(seed)
    result = runner.invoke(cli.app, ["audit"])
    assert result.exit_code == 0


# --- normalization: register --auto alias -----------------------------------


def test_register_accepts_auto_alias(seed):
    result = runner.invoke(
        cli.app,
        ["register", "-n", "svc", "-c", "echo hi", "--auto"],
    )
    assert result.exit_code == 0
    names = [s["name"] for s in seed.get("/api/services").json()]
    assert "svc" in names


# --- upgrade ----------------------------------------------------------------


def test_upgrade_forces_a_fresh_remote_check(monkeypatch):
    captured: dict = {}

    def fake_check(**kwargs):
        captured.update(kwargs)
        return None  # "up to date" → no subprocess, clean exit

    monkeypatch.setattr(cli.update_mod, "check_for_update", fake_check)
    monkeypatch.setattr(cli.update_mod, "installed_version", lambda: "0.1.0")
    monkeypatch.setattr(cli.update_mod, "notify_if_outdated", lambda: None)

    result = runner.invoke(cli.app, ["upgrade"])
    assert result.exit_code == 0
    assert captured.get("ttl_hours") == 0  # bypasses the 24h notifier cache


# --- doctor -----------------------------------------------------------------


def test_doctor_reports_clean(seed):
    _register(seed)
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0
    assert "No port conflicts" in result.stdout


# --- daemon-port ------------------------------------------------------------


def test_daemon_port_show(seed):
    result = runner.invoke(cli.app, ["daemon-port"])
    assert result.exit_code == 0
    assert str(config.daemon_port()) in result.stdout


def test_daemon_port_set(seed):
    result = runner.invoke(cli.app, ["daemon-port", "--set", "45000"])
    assert result.exit_code == 0
    assert config.daemon_port() == 45000


def test_daemon_port_set_and_regenerate_conflict(seed):
    result = runner.invoke(cli.app, ["daemon-port", "--set", "45000", "--regenerate"])
    assert result.exit_code == 1


# --- init: random fixed ports -----------------------------------------------


def test_init_writes_fixed_random_ports(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTMAN_HOME", str(tmp_path / "home"))
    config.refresh_from_env()
    monkeypatch.setattr(cli, "_daemon_running", lambda: False)
    monkeypatch.setattr(cli.update_mod, "notify_if_outdated", lambda: None)
    monkeypatch.setattr(ports, "list_listening", lambda: [])

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "package.json").write_text(
        json.dumps({"scripts": {"dev": "vite"}, "devDependencies": {"vite": "^5"}})
    )

    result = runner.invoke(cli.app, ["init", str(proj)])
    assert result.exit_code == 0, result.stdout
    text = (proj / "portman.yaml").read_text()
    assert "port: auto" not in text  # defaults replaced with concrete ports

    from portman.manifest import parse

    services, _ = parse(str(proj))
    assert services[0].port is not None
    assert config.PORT_RANGE_START <= services[0].port <= config.PORT_RANGE_END
