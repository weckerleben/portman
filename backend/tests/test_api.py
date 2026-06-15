"""API wiring tests via FastAPI's TestClient.

System introspection is stubbed (no real listening sockets) so the live-system
endpoints are deterministic. Process lifecycle is covered by the supervisor unit
tests and the end-to-end smoke described in the README.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from portman import config, ports, runtime
from portman.app import create_app


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
