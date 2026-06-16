"""Broad CLI command coverage.

Complements test_cli.py: exercises every command path, including the
subprocess/uvicorn/browser commands (mocked) and the service lifecycle (with the
supervisor singleton faked so no real processes are spawned).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from portman import cli, config, db, ports, runtime
from portman.app import create_app
from portman.ports import ListeningPort
from portman.supervisor import ProcInfo

runner = CliRunner()


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolated PORTMAN_HOME with no daemon and the update nudge silenced."""
    monkeypatch.delenv("PORTMAN_PORT", raising=False)
    monkeypatch.setenv("PORTMAN_HOME", str(tmp_path))
    config.refresh_from_env()
    monkeypatch.setattr(cli.update_mod, "notify_if_outdated", lambda: None)
    monkeypatch.setattr(ports, "list_listening", lambda: [])
    yield tmp_path


@pytest.fixture
def daemon(home, monkeypatch):
    """A live in-process daemon the CLI talks to via an injected TestClient."""
    runtime.scanner._lister = lambda: []
    runtime.scanner._seen_unauthorized = set()
    runtime.supervisor._procs.clear()
    db.init_db()
    app = create_app()
    monkeypatch.setattr(cli, "_client", lambda: TestClient(app))
    monkeypatch.setattr(cli, "_daemon_running", lambda: True)
    yield TestClient(app)
    db.dispose()


def _register(client, **kwargs) -> dict:
    payload = {"name": "web", "command": "python -m http.server", "port": 8123}
    payload.update(kwargs)
    resp = client.post("/api/services", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- guard: daemon required -------------------------------------------------


def test_command_requires_daemon(home, monkeypatch):
    monkeypatch.setattr(cli, "_daemon_running", lambda: False)
    result = runner.invoke(cli.app, ["ls"])
    assert result.exit_code == 1
    assert "daemon is not running" in result.stdout


# --- inspection commands ----------------------------------------------------


def test_ls_renders_a_listening_port(daemon, monkeypatch):
    # A live unauthorized listener so the ports table body is exercised.
    monkeypatch.setattr(
        runtime.scanner,
        "_lister",
        lambda: [ListeningPort(port=4555, pid=77, name="node", cmdline="node x.js")],
    )
    result = runner.invoke(cli.app, ["ls"])
    assert result.exit_code == 0
    assert "4555" in result.stdout


def test_services_lists_registered(daemon):
    _register(daemon)
    result = runner.invoke(cli.app, ["services"])
    assert result.exit_code == 0
    assert "web" in result.stdout


def test_reservations_and_audit_with_detail(daemon):
    daemon.post("/api/reservations", json={"port": 9100, "purpose": "db"})
    assert runner.invoke(cli.app, ["reservations"]).exit_code == 0
    # audit rows carry dict details (rendered as compact JSON).
    result = runner.invoke(cli.app, ["audit"])
    assert result.exit_code == 0


def test_doctor_reports_conflicts(daemon):
    _register(daemon, name="a", port=5000)
    _register(daemon, name="b", port=5000)
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 1
    assert "5000" in result.stdout


# --- mutations over the API -------------------------------------------------


def test_reserve_auto_and_new(daemon):
    assert runner.invoke(cli.app, ["reserve", "--auto", "--for", "cache"]).exit_code == 0
    result = runner.invoke(cli.app, ["new"])
    assert result.exit_code == 0


def test_register_error_surfaces(daemon, monkeypatch):
    # Force the API to 409 so the error branch of _print_response runs.
    def boom(*a, **k):
        raise RuntimeError("no free port")

    monkeypatch.setattr(runtime, "create_service", boom)
    result = runner.invoke(cli.app, ["register", "-n", "x", "-c", "echo hi", "--auto"])
    assert result.exit_code == 1
    assert "Error" in result.stdout


def test_release_and_kill_port(daemon, monkeypatch):
    daemon.post("/api/reservations", json={"port": 9100, "purpose": "db"})
    assert runner.invoke(cli.app, ["release", "9100"]).exit_code == 0
    monkeypatch.setattr(runtime.supervisor, "kill_port", lambda port: [123])
    assert runner.invoke(cli.app, ["kill-port", "8080"]).exit_code == 0


# --- service lifecycle (supervisor faked) -----------------------------------


@pytest.fixture
def faked_supervisor(monkeypatch):
    state = {"running": False}

    def fake_start(spec):
        state["running"] = True
        return ProcInfo(key=spec.key, pid=4242, run_id=spec.run_id, log_path="", running=True)

    def fake_stop(key, **kw):
        state["running"] = False
        return None

    monkeypatch.setattr(runtime.supervisor, "start", fake_start)
    monkeypatch.setattr(runtime.supervisor, "stop", fake_stop)
    monkeypatch.setattr(runtime.supervisor, "kill", fake_stop)
    monkeypatch.setattr(runtime.supervisor, "is_running", lambda key: state["running"])
    monkeypatch.setattr(runtime.supervisor, "info", lambda key: None)
    return state


def test_start_stop_restart_kill(daemon, faked_supervisor):
    _register(daemon)
    assert runner.invoke(cli.app, ["start", "web"]).exit_code == 0
    assert runner.invoke(cli.app, ["restart", "web"]).exit_code == 0
    assert runner.invoke(cli.app, ["stop", "web"]).exit_code == 0
    assert runner.invoke(cli.app, ["kill", "web"]).exit_code == 0


def test_logs_after_a_run(daemon, faked_supervisor):
    _register(daemon)
    runner.invoke(cli.app, ["start", "web"])
    result = runner.invoke(cli.app, ["logs", "web"])
    assert result.exit_code == 0


# --- import -----------------------------------------------------------------


def test_import_reports_reassignments(daemon, home, monkeypatch):
    proj = home / "proj"
    proj.mkdir()
    (proj / "portman.yaml").write_text("services:\n  - name: web\n    command: x\n    port: 3000\n")
    monkeypatch.setattr(
        ports, "list_listening", lambda: [ListeningPort(port=3000, pid=1, name="busy")]
    )
    result = runner.invoke(cli.app, ["import", str(proj)])
    assert result.exit_code == 0
    assert "reassigned" in result.stdout.lower()


def test_import_error_on_missing_manifest(daemon, home):
    result = runner.invoke(cli.app, ["import", str(home / "nope")])
    assert result.exit_code == 1


# --- init -------------------------------------------------------------------


def _node_project(home):
    proj = home / "proj"
    proj.mkdir()
    (proj / "package.json").write_text(
        json.dumps({"scripts": {"dev": "vite"}, "devDependencies": {"vite": "^5"}})
    )
    return proj


def test_init_existing_without_force_errors(home, monkeypatch):
    monkeypatch.setattr(cli, "_daemon_running", lambda: False)
    proj = _node_project(home)
    (proj / "portman.yaml").write_text("services: []\n")
    result = runner.invoke(cli.app, ["init", str(proj)])
    assert result.exit_code == 1
    assert "already exists" in result.stdout


def test_init_blank_template(home, monkeypatch):
    monkeypatch.setattr(cli, "_daemon_running", lambda: False)
    proj = _node_project(home)
    result = runner.invoke(cli.app, ["init", str(proj), "--blank"])
    assert result.exit_code == 0
    assert "services:" in (proj / "portman.yaml").read_text()


def test_init_reuses_existing_ports_on_force(home, monkeypatch):
    monkeypatch.setattr(cli, "_daemon_running", lambda: False)
    proj = _node_project(home)
    # The root package.json is detected as service "web"; pre-seed its port.
    (proj / "portman.yaml").write_text(
        "services:\n  - name: web\n    command: x\n    port: 41111\n"
    )
    result = runner.invoke(cli.app, ["init", str(proj), "--force"])
    assert result.exit_code == 0
    from portman.manifest import parse

    services, _ = parse(str(proj))
    assert any(s.port == 41111 for s in services)


def test_init_reserves_when_daemon_running(daemon, home):
    proj = _node_project(home)
    result = runner.invoke(cli.app, ["init", str(proj)])
    assert result.exit_code == 0
    assert "Reserved" in result.stdout
    assert daemon.get("/api/reservations").json()  # ports were reserved


def test_init_ai_enrichment(home, monkeypatch):
    monkeypatch.setattr(cli, "_daemon_running", lambda: False)
    from portman import detect

    proj = home / "empty"
    proj.mkdir()
    monkeypatch.setattr(cli.credentials, "get_api_key", lambda: "sk-ant-test")
    monkeypatch.setattr(
        cli.ai_mod,
        "enrich_services",
        lambda root, existing, key: [detect.DetectedService(name="api", command="run $PORT")],
    )
    result = runner.invoke(cli.app, ["init", str(proj), "--ai"])
    assert result.exit_code == 0


def test_init_ai_failure_is_reported(home, monkeypatch):
    monkeypatch.setattr(cli, "_daemon_running", lambda: False)
    proj = home / "empty2"
    proj.mkdir()
    monkeypatch.setattr(cli.credentials, "get_api_key", lambda: "sk-ant-test")

    def boom(root, existing, key):
        raise cli.ai_mod.AIError("model unavailable")

    monkeypatch.setattr(cli.ai_mod, "enrich_services", boom)
    result = runner.invoke(cli.app, ["init", str(proj), "--ai"])
    assert result.exit_code == 0
    assert "failed" in result.stdout.lower()


# --- credentials ------------------------------------------------------------


def test_login_with_key_and_logout(home):
    assert runner.invoke(cli.app, ["login", "--key", "sk-ant-abc"]).exit_code == 0
    assert runner.invoke(cli.app, ["logout"]).exit_code == 0


# --- daemon-port: regenerate + restart note ---------------------------------


def test_daemon_port_regenerate_notes_restart(daemon, monkeypatch):
    monkeypatch.setattr(config, "_random_daemon_port", lambda **_: 50505)
    result = runner.invoke(cli.app, ["daemon-port", "--regenerate"])
    assert result.exit_code == 0
    assert "50505" in result.stdout
    assert "Restart" in result.stdout


# --- daemon lifecycle: serve / up / down / open / upgrade -------------------


def test_serve_invokes_uvicorn(home, monkeypatch):
    import uvicorn

    called = {}
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: called.update(k))
    result = runner.invoke(cli.app, ["serve"])
    assert result.exit_code == 0
    assert called["port"] == config.daemon_port()


def test_open_launches_browser(home, monkeypatch):
    opened = {}
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.setdefault("url", url))
    assert runner.invoke(cli.app, ["open"]).exit_code == 0
    assert opened["url"].endswith("/")


def test_up_when_already_running(home, monkeypatch):
    monkeypatch.setattr(cli, "_daemon_running", lambda: True)
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: None)
    result = runner.invoke(cli.app, ["up", "--no-open"])
    assert result.exit_code == 0
    assert "already running" in result.stdout


def test_up_starts_daemon(home, monkeypatch):
    # Not running on first check, healthy after "launch".
    # False (already-running check), False (wait-loop body once), True (loop exit),
    # True (final health check → success).
    checks = iter([False, False, True, True])
    monkeypatch.setattr(cli, "_daemon_running", lambda: next(checks, True))

    class FakeProc:
        pid = 9999

    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **k: FakeProc())
    monkeypatch.setattr(cli.config, "ensure_free_daemon_port", lambda: 50001)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: None)
    result = runner.invoke(cli.app, ["up"])
    assert result.exit_code == 0
    assert "portman is up" in result.stdout
    assert config.PID_FILE.read_text() == "9999"


def test_down_without_pid_file(home):
    result = runner.invoke(cli.app, ["down"])
    assert result.exit_code == 0
    assert "not running" in result.stdout


def test_down_signals_pid(home, monkeypatch):
    config.ensure_dirs()
    config.PID_FILE.write_text("12345")
    killed = {}
    monkeypatch.setattr(cli.os, "kill", lambda pid, sig: killed.update(pid=pid))
    result = runner.invoke(cli.app, ["down"])
    assert result.exit_code == 0
    assert killed["pid"] == 12345
    assert not config.PID_FILE.exists()


def test_down_handles_dead_pid(home, monkeypatch):
    config.ensure_dirs()
    config.PID_FILE.write_text("12345")
    monkeypatch.setattr(cli.os, "kill", lambda pid, sig: (_ for _ in ()).throw(ProcessLookupError))
    result = runner.invoke(cli.app, ["down"])
    assert result.exit_code == 0
    assert "not running" in result.stdout


def test_upgrade_runs_installer(home, monkeypatch):
    monkeypatch.setattr(cli.update_mod, "check_for_update", lambda ttl_hours=0: "9.9.9")
    monkeypatch.setattr(cli.update_mod, "installed_version", lambda: "0.1.0")
    monkeypatch.setattr(
        cli.update_mod, "detect_upgrade_command", lambda: ["pip", "install", "-U", "portreeve"]
    )
    monkeypatch.setattr(cli.subprocess, "call", lambda cmd: 0)
    result = runner.invoke(cli.app, ["upgrade"])
    assert result.exit_code == 0
    assert "Upgrading" in result.stdout


def test_upgrade_up_to_date(home, monkeypatch):
    monkeypatch.setattr(cli.update_mod, "check_for_update", lambda ttl_hours=0: None)
    monkeypatch.setattr(cli.update_mod, "installed_version", lambda: "9.9.9")
    result = runner.invoke(cli.app, ["upgrade"])
    assert result.exit_code == 0
    assert "up to date" in result.stdout


def test_upgrade_missing_installer(home, monkeypatch):
    monkeypatch.setattr(cli.update_mod, "check_for_update", lambda ttl_hours=0: "9.9.9")
    monkeypatch.setattr(cli.update_mod, "installed_version", lambda: "0.1.0")
    monkeypatch.setattr(cli.update_mod, "detect_upgrade_command", lambda: ["nope"])

    def boom(cmd):
        raise FileNotFoundError

    monkeypatch.setattr(cli.subprocess, "call", boom)
    result = runner.invoke(cli.app, ["upgrade"])
    assert result.exit_code == 1
    assert "not found" in result.stdout


# --- status + low-level client helpers --------------------------------------


def test_status_running(daemon):
    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 0
    assert "running" in result.stdout


def test_status_not_running(home):
    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 0
    assert "not running" in result.stdout


def test_client_and_daemon_check_against_no_server(home):
    assert cli._daemon_running() is False  # real httpx call, connection refused
    client = cli._client()
    client.close()


def test_daemon_used_ports_empty_without_daemon(home):
    assert cli._daemon_used_ports() == set()


def test_merge_skips_duplicate_names():
    from portman import detect

    a = [detect.DetectedService(name="x", command="1")]
    b = [detect.DetectedService(name="x", command="2"), detect.DetectedService(name="y", command="3")]
    assert [s.name for s in cli._merge(a, b)] == ["x", "y"]


def test_logs_prints_captured_lines(daemon, home):
    from portman.models import Run

    sid = _register(daemon)["id"]
    logf = home / "r.log"
    logf.write_text("alpha\nbeta\n")
    with db.session_scope() as session:
        session.add(Run(service_id=sid, status="running", log_path=str(logf)))
    result = runner.invoke(cli.app, ["logs", "web"])
    assert "beta" in result.stdout


# --- up: restart + failure branches -----------------------------------------


def test_up_restart_when_running(home, monkeypatch):
    config.ensure_dirs()
    config.PID_FILE.write_text("4242")
    # restart-check, stop-loop body once, stop-loop exit, already-running check.
    checks = iter([True, True, False, True])
    monkeypatch.setattr(cli, "_daemon_running", lambda: next(checks, True))
    monkeypatch.setattr(cli.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    result = runner.invoke(cli.app, ["up", "--restart", "--no-open"])
    assert result.exit_code == 0
    assert "already running" in result.stdout


def test_up_reports_failure_to_start(home, monkeypatch):
    monkeypatch.setattr(cli, "_daemon_running", lambda: False)
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **k: type("P", (), {"pid": 1})())
    monkeypatch.setattr(cli.config, "ensure_free_daemon_port", lambda: 50001)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    mono = iter([0, 1000])
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(mono, 1000))
    result = runner.invoke(cli.app, ["up"])
    assert result.exit_code == 1
    assert "failed to start" in result.stdout


# --- init: corrupt existing manifest + AI key prompt ------------------------


def test_init_force_with_corrupt_existing_manifest(home, monkeypatch):
    monkeypatch.setattr(cli, "_daemon_running", lambda: False)
    proj = _node_project(home)
    (proj / "portman.yaml").write_text("foo: [unclosed")
    result = runner.invoke(cli.app, ["init", str(proj), "--force"])
    assert result.exit_code == 0


def test_init_ai_prompts_for_missing_key(home, monkeypatch):
    from portman import detect

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(cli, "_daemon_running", lambda: False)
    proj = home / "empty3"
    proj.mkdir()
    monkeypatch.setattr(cli.credentials, "get_api_key", lambda: None)
    saved = {}
    monkeypatch.setattr(cli.credentials, "set_api_key", lambda k: saved.update(k=k))
    monkeypatch.setattr(
        cli.ai_mod,
        "enrich_services",
        lambda root, existing, key: [detect.DetectedService(name="api", command="x")],
    )
    result = runner.invoke(cli.app, ["init", str(proj), "--ai"], input="sk-typed\n")
    assert result.exit_code == 0
    assert saved["k"] == "sk-typed"


# --- login prompt -----------------------------------------------------------


def test_login_prompts_for_key(home, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = runner.invoke(cli.app, ["login"], input="sk-ant-prompted\n")
    assert result.exit_code == 0
    assert cli.credentials.get_api_key() == "sk-ant-prompted"


# --- interactive branches (called directly; CliRunner swaps stdin) ----------


def test_unregister_decline_keeps_service(daemon, monkeypatch):
    import typer

    _register(daemon)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.typer, "confirm", lambda *a, **k: False)  # user says no
    with pytest.raises(typer.Exit) as exc:
        cli.unregister("web", yes=False)
    assert exc.value.exit_code == 0
    assert daemon.get("/api/services").json()  # still registered


def test_init_offers_ai_when_nothing_detected(home, monkeypatch):
    monkeypatch.setattr(cli, "_daemon_running", lambda: False)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.typer, "confirm", lambda *a, **k: False)  # decline AI
    proj = home / "empty4"
    proj.mkdir()
    cli.init(str(proj), force=False, blank=False, ai=False)
    assert (proj / "portman.yaml").exists()


def test_module_entrypoint(monkeypatch):
    import runpy
    import sys

    monkeypatch.setattr(cli.sys, "argv", ["portman"])
    # Drop the cached module so run_module executes it cleanly as __main__
    # (avoids runpy's "found in sys.modules" RuntimeWarning). monkeypatch
    # restores the original module after the test.
    monkeypatch.delitem(sys.modules, "portman.cli", raising=False)
    with pytest.raises(SystemExit):  # no args → help, then exits
        runpy.run_module("portman.cli", run_name="__main__")
