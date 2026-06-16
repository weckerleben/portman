"""Tests for per-project manifest parsing and import."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from portman import db, ports
from portman.manifest import ManifestError, import_manifest, parse
from portman.models import PortReservation, Service
from portman.ports import ListeningPort

MANIFEST = """
services:
  - name: web
    command: "npm run dev"
    port: 3000
    description: "Next.js dev server"
  - name: api
    command: "uvicorn app:app"
    port: auto
    cwd: backend
    auto_restart: true
"""


def _write(tmp_path, text: str):
    path = tmp_path / "portman.yaml"
    path.write_text(text)
    return path


def test_parse_reads_services(tmp_path):
    _write(tmp_path, MANIFEST)
    services, manifest_path = parse(str(tmp_path))
    assert [s.name for s in services] == ["web", "api"]

    web, api = services
    assert web.port == 3000 and web.auto_port is False
    assert api.auto_port is True and api.port is None
    assert api.auto_restart is True
    # cwd is resolved relative to the manifest directory
    assert api.cwd == str((tmp_path / "backend").resolve())
    assert manifest_path.name == "portman.yaml"


def test_parse_accepts_directory_or_file(tmp_path):
    path = _write(tmp_path, MANIFEST)
    from_dir, _ = parse(str(tmp_path))
    from_file, _ = parse(str(path))
    assert [s.name for s in from_dir] == [s.name for s in from_file]


def test_parse_rejects_missing_and_malformed(tmp_path):
    with pytest.raises(ManifestError):
        parse(str(tmp_path))  # no file
    _write(tmp_path, "services: []")
    with pytest.raises(ManifestError):
        parse(str(tmp_path))
    _write(tmp_path, "services:\n  - name: x")  # missing command
    with pytest.raises(ManifestError):
        parse(str(tmp_path))


def test_import_creates_then_updates_idempotently(tmp_path, temp_db):
    _write(tmp_path, MANIFEST)

    with db.session_scope() as session:
        result = import_manifest(session, str(tmp_path))
    assert sorted(result["created"]) == ["api", "web"]

    with db.session_scope() as session:
        services = list(session.scalars(select(Service)))
        assert len(services) == 2
        assert all(s.source == "manifest" for s in services)

    # Re-import after editing the description → updates, does not duplicate.
    _write(tmp_path, MANIFEST.replace("Next.js dev server", "Edited"))
    with db.session_scope() as session:
        result = import_manifest(session, str(tmp_path))
    assert sorted(result["updated"]) == ["api", "web"]

    with db.session_scope() as session:
        services = list(session.scalars(select(Service)))
        assert len(services) == 2
        web = next(s for s in services if s.name == "web")
        assert web.description == "Edited"


def test_parse_rejects_invalid_yaml(tmp_path):
    _write(tmp_path, "foo: [unclosed")
    with pytest.raises(ManifestError):
        parse(str(tmp_path))


def test_parse_rejects_non_mapping_entry(tmp_path):
    _write(tmp_path, "services:\n  - just a string\n")
    with pytest.raises(ManifestError):
        parse(str(tmp_path))


def test_import_reassigns_busy_fixed_port(tmp_path, temp_db, monkeypatch):
    # Pretend something foreign already listens on the requested port 3000.
    monkeypatch.setattr(
        ports, "list_listening", lambda: [ListeningPort(port=3000, pid=999, name="other")]
    )
    _write(tmp_path, "services:\n  - name: web\n    command: x\n    port: 3000\n")

    with db.session_scope() as session:
        result = import_manifest(session, str(tmp_path))

    assert result["reassigned"][0]["service"] == "web"
    assert result["reassigned"][0]["requested"] == 3000
    with db.session_scope() as session:
        web = session.scalars(select(Service)).first()
        assert web.assigned_port != 3000


def test_import_adopts_init_reservation(tmp_path, temp_db, monkeypatch):
    monkeypatch.setattr(ports, "list_listening", lambda: [])
    # init had reserved 23456 for "web"; importing should keep that port and
    # release the placeholder reservation (the service now owns it).
    with db.session_scope() as session:
        session.add(PortReservation(port=23456, purpose="portman-init:web"))

    _write(tmp_path, "services:\n  - name: web\n    command: x\n    port: 23456\n")
    with db.session_scope() as session:
        result = import_manifest(session, str(tmp_path))

    assert result["reassigned"] == []  # its own reservation is not a conflict
    with db.session_scope() as session:
        web = session.scalars(select(Service)).first()
        assert web.assigned_port == 23456
        assert session.scalars(select(PortReservation)).first() is None
