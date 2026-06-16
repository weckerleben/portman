"""API wiring tests via FastAPI's TestClient.

System introspection is stubbed (no real listening sockets) so the live-system
endpoints are deterministic. Process lifecycle is covered by the supervisor unit
tests and the end-to-end smoke described in the README.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from portman import config, db, ports, runtime
from portman.app import create_app
from portman.models import Run


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTMAN_HOME", str(tmp_path))
    config.refresh_from_env()
    # Pretend nothing else is listening so classification is deterministic.
    monkeypatch.setattr(ports, "list_listening", lambda: [])
    runtime.scanner._lister = lambda: []
    runtime.scanner._seen_unauthorized = set()
    runtime.supervisor._procs.clear()
    with TestClient(create_app()) as test_client:
        yield test_client


def _create(client, **kwargs) -> dict:
    payload = {"name": "web", "command": "python -m http.server"}
    payload.update(kwargs)
    resp = client.post("/api/services", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_create_list_get_delete_service(client):
    created = _create(client, description="dev server")
    sid = created["id"]
    assert created["slug"] == "web"
    assert created["running"] is False

    listed = client.get("/api/services").json()
    assert [s["id"] for s in listed] == [sid]

    detail = client.get(f"/api/services/{sid}").json()
    assert detail["description"] == "dev server"
    assert detail["runs"] == []

    assert client.delete(f"/api/services/{sid}").status_code == 204
    assert client.get("/api/services").json() == []


def test_get_missing_service_is_404(client):
    assert client.get("/api/services/999").status_code == 404


def test_create_service_auto_port_assigns_a_port(client):
    created = _create(client, auto_port=True)
    assert created["assigned_port"] is not None
    assert 20000 <= created["assigned_port"] <= 60000


def test_reserve_list_and_release(client):
    res = client.post("/api/reservations", json={"port": 4321, "purpose": "future api"})
    assert res.status_code == 201
    rid = res.json()["id"]
    assert res.json()["port"] == 4321

    listed = client.get("/api/reservations").json()
    assert [r["port"] for r in listed] == [4321]

    assert client.delete(f"/api/reservations/{rid}").status_code == 204
    assert client.get("/api/reservations").json() == []


def test_reserve_requires_port_or_auto(client):
    assert client.post("/api/reservations", json={"purpose": "x"}).status_code == 400


def test_generate_port_returns_free_port(client):
    body = client.post("/api/ports/generate").json()
    assert 20000 <= body["port"] <= 60000


def test_ports_view_shape(client):
    _create(client)
    view = client.get("/api/ports").json()
    assert set(view) >= {"ports", "services", "reservations", "counts"}
    assert view["counts"]["managed"] == 0  # nothing actually running


def test_audit_records_authorization(client):
    _create(client)
    events = client.get("/api/audit").json()
    assert any(e["type"] == "authorize" for e in events)


def test_create_service_reassigns_a_busy_fixed_port(client, monkeypatch):
    monkeypatch.setattr(
        ports, "list_listening", lambda: [ports.ListeningPort(port=7000, pid=1, name="other")]
    )
    created = _create(client, port=7000)
    assert created["assigned_port"] != 7000


def test_reserve_is_idempotent(client):
    client.post("/api/reservations", json={"port": 6000, "purpose": "x"})
    client.post("/api/reservations", json={"port": 6000, "purpose": "x"})
    reserved = [r for r in client.get("/api/reservations").json() if r["port"] == 6000]
    assert len(reserved) == 1


def test_doctor_is_clean_without_conflicts(client):
    _create(client)
    report = client.get("/api/doctor").json()
    assert report["ok"] is True
    assert report["conflicts"] == []
    assert report["daemon_port"]


def test_doctor_flags_duplicate_assignment(client):
    # Two idle services on the same fixed port: only one could ever bind it.
    _create(client, name="a", port=5000)
    _create(client, name="b", port=5000)
    report = client.get("/api/doctor").json()
    assert report["ok"] is False
    assert any(c["type"] == "duplicate_assignment" and c["port"] == 5000 for c in report["conflicts"])


def test_doctor_flags_foreign_process_on_service_port(client, monkeypatch):
    _create(client, port=8200)  # assigned 8200, but not running
    monkeypatch.setattr(
        ports,
        "list_listening",
        lambda: [ports.ListeningPort(port=8200, pid=42, name="rogue", cmdline="rogue --serve")],
    )
    report = client.get("/api/doctor").json()
    assert any(c["type"] == "port_taken" and c["port"] == 8200 for c in report["conflicts"])


def test_doctor_flags_reserved_port_in_use(client, monkeypatch):
    client.post("/api/reservations", json={"port": 8300, "purpose": "db"})
    monkeypatch.setattr(
        ports, "list_listening", lambda: [ports.ListeningPort(port=8300, pid=7, name="pg")]
    )
    report = client.get("/api/doctor").json()
    assert any(c["type"] == "reservation_taken" and c["port"] == 8300 for c in report["conflicts"])


# --- service lifecycle endpoints (error + success paths) --------------------


def test_lifecycle_endpoints_404_for_missing_service(client):
    for action in ("start", "stop", "kill", "restart"):
        assert client.post(f"/api/services/999/{action}").status_code == 404


def test_delete_running_service_is_rejected(client, monkeypatch):
    sid = _create(client)["id"]
    monkeypatch.setattr(runtime.supervisor, "is_running", lambda key: True)
    resp = client.delete(f"/api/services/{sid}")
    assert resp.status_code == 400
    assert "stop the service" in resp.json()["detail"]


def test_start_then_already_running_is_400(client, monkeypatch):
    sid = _create(client, auto_port=True)["id"]
    from portman.supervisor import ProcInfo

    monkeypatch.setattr(
        runtime.supervisor,
        "start",
        lambda spec: ProcInfo(key=spec.key, pid=1, run_id=spec.run_id, log_path="", running=True),
    )
    assert client.post(f"/api/services/{sid}/start").status_code == 200
    monkeypatch.setattr(runtime.supervisor, "is_running", lambda key: True)
    assert client.post(f"/api/services/{sid}/start").status_code == 400


def test_delete_missing_reservation_is_404(client):
    assert client.delete("/api/reservations/999").status_code == 404


def test_reserve_auto_409_when_none_free(client, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("no free port")

    monkeypatch.setattr(ports, "find_free_port", boom)
    assert client.post("/api/reservations", json={"auto": True}).status_code == 409


def test_generate_port_409_when_none_free(client, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("no free port")

    monkeypatch.setattr(ports, "find_free_port", boom)
    assert client.post("/api/ports/generate").status_code == 409


def test_kill_port_endpoint(client, monkeypatch):
    monkeypatch.setattr(runtime.supervisor, "kill_port", lambda port: [555])
    body = client.post("/api/ports/7000/kill").json()
    assert body == {"port": 7000, "killed_pids": [555]}


def test_import_manifest_bad_path_is_400(client):
    assert client.post("/api/manifest/import", json={"path": "/no/such/dir"}).status_code == 400


def test_run_log_returns_lines(client, tmp_path):
    sid = _create(client)["id"]
    log = tmp_path / "run.log"
    log.write_text("line one\nline two\n")
    with db.session_scope() as session:
        run = Run(service_id=sid, status="running", log_path=str(log))
        session.add(run)
        session.flush()
        run_id = run.id
    data = client.get(f"/api/runs/{run_id}/log", params={"tail": 1}).json()
    assert data["lines"] == ["line two"]


def test_run_log_missing_file_is_empty(client):
    sid = _create(client)["id"]
    with db.session_scope() as session:
        run = Run(service_id=sid, status="running", log_path="/no/such/file.log")
        session.add(run)
        session.flush()
        run_id = run.id
    assert client.get(f"/api/runs/{run_id}/log").json()["lines"] == []


# --- websockets -------------------------------------------------------------


def test_ws_status_streams_a_view(client):
    with client.websocket_connect("/ws/status") as ws:
        view = ws.receive_json()
    assert set(view) >= {"ports", "services", "counts"}


def test_ws_logs_reports_missing_log(client):
    with client.websocket_connect("/ws/logs/999") as ws:
        assert ws.receive_json() == {"error": "log not found"}


def test_ws_status_handles_disconnect(client, monkeypatch):
    from fastapi import WebSocketDisconnect

    from portman import api

    async def fake_sleep(_delay):
        raise WebSocketDisconnect(code=1000)  # simulate the client going away mid-wait

    monkeypatch.setattr(api.asyncio, "sleep", fake_sleep)
    with client.websocket_connect("/ws/status") as ws:
        ws.receive_json()  # first view sent before the (disconnecting) sleep


def test_ws_logs_handles_disconnect(client, tmp_path, monkeypatch):
    from fastapi import WebSocketDisconnect

    from portman import api

    sid = _create(client)["id"]
    log = tmp_path / "run.log"
    log.write_text("backlog line\n")
    with db.session_scope() as session:
        run = Run(service_id=sid, status="running", log_path=str(log))
        session.add(run)
        session.flush()
        run_id = run.id

    async def fake_sleep(_delay):
        raise WebSocketDisconnect(code=1000)

    monkeypatch.setattr(api.asyncio, "sleep", fake_sleep)
    with client.websocket_connect(f"/ws/logs/{run_id}") as ws:
        ws.receive_json()  # backlog; the follow-up read hits the disconnecting sleep


def test_ws_logs_streams_new_chunk_after_backlog(client, tmp_path, monkeypatch):
    from fastapi import WebSocketDisconnect

    from portman import api

    sid = _create(client)["id"]
    log = tmp_path / "run.log"
    log.write_text("")  # empty backlog so the new chunk arrives in the follow loop
    with db.session_scope() as session:
        run = Run(service_id=sid, status="running", log_path=str(log))
        session.add(run)
        session.flush()
        run_id = run.id

    state = {"n": 0}

    async def fake_sleep(_delay):
        state["n"] += 1
        if state["n"] == 1:
            with open(log, "a") as handle:  # new data appears mid-stream
                handle.write("live chunk\n")
            return
        raise WebSocketDisconnect(code=1000)

    monkeypatch.setattr(api.asyncio, "sleep", fake_sleep)
    with client.websocket_connect(f"/ws/logs/{run_id}") as ws:
        chunk = ws.receive_json()
    assert "live chunk" in chunk["chunk"]


def test_ws_logs_streams_backlog(client, tmp_path):
    sid = _create(client)["id"]
    log = tmp_path / "run.log"
    log.write_text("hello from the run\n")
    with db.session_scope() as session:
        run = Run(service_id=sid, status="running", log_path=str(log))
        session.add(run)
        session.flush()
        run_id = run.id
    with client.websocket_connect(f"/ws/logs/{run_id}") as ws:
        chunk = ws.receive_json()
    assert "hello from the run" in chunk["chunk"]
