"""Tests for static project detection and manifest rendering."""

from __future__ import annotations

import json

import yaml

from portman import detect, manifest


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_detects_vite_node_app(tmp_path):
    _write(
        tmp_path,
        "frontend/package.json",
        json.dumps({"scripts": {"dev": "vite"}, "devDependencies": {"vite": "^5"}}),
    )
    services = detect.detect_services(tmp_path)
    assert len(services) == 1
    svc = services[0]
    assert svc.name == "frontend"
    assert svc.cwd == "frontend"
    assert svc.port == 5173
    assert "$PORT" in svc.command
    assert svc.note  # explains why it was detected


def test_detects_fastapi_python_app(tmp_path):
    _write(tmp_path, "pyproject.toml", '[project]\ndependencies = ["fastapi", "uvicorn"]\n')
    services = detect.detect_services(tmp_path)
    assert len(services) == 1
    svc = services[0]
    assert "uvicorn" in svc.command
    assert svc.auto_port is True


def test_detects_python_backend_in_subdir(tmp_path):
    _write(tmp_path, "backend/pyproject.toml", '[project]\ndependencies = ["fastapi"]\n')
    services = detect.detect_services(tmp_path)
    assert len(services) == 1
    svc = services[0]
    assert svc.name == "backend"
    assert svc.cwd == "backend"
    assert svc.auto_port is True


def test_detects_django_app(tmp_path):
    _write(tmp_path, "manage.py", "# django entrypoint\n")
    services = detect.detect_services(tmp_path)
    assert len(services) == 1
    svc = services[0]
    assert "runserver" in svc.command
    assert svc.port == 8000


def test_detects_compose_services(tmp_path):
    _write(
        tmp_path,
        "docker-compose.yml",
        "services:\n  db:\n    image: postgres\n    ports:\n      - \"5432:5432\"\n",
    )
    services = detect.detect_services(tmp_path)
    assert len(services) == 1
    svc = services[0]
    assert svc.name == "db"
    assert svc.port == 5432
    assert "docker compose" in svc.command


def test_returns_empty_for_unknown_project(tmp_path):
    _write(tmp_path, "README.md", "# nothing to see here\n")
    assert detect.detect_services(tmp_path) == []


def test_render_roundtrips_through_manifest_parser(tmp_path):
    services = [
        detect.DetectedService(
            name="web",
            command="npm run dev -- --port $PORT",
            description="Vite dev server",
            cwd="frontend",
            port=5173,
            note="package.json with vite",
        ),
        detect.DetectedService(
            name="api",
            command="uvicorn app:app --port $PORT",
            cwd="backend",
            auto_port=True,
            note="pyproject.toml with fastapi",
        ),
    ]
    text = detect.render_manifest(services)
    # Comments carry the detection rationale.
    assert "# package.json with vite" in text
    (tmp_path / "portman.yaml").write_text(text)

    parsed, _ = manifest.parse(str(tmp_path))
    assert [s.name for s in parsed] == ["web", "api"]
    web, api = parsed
    assert web.port == 5173
    assert api.auto_port is True


def test_detects_flask_app(tmp_path):
    _write(tmp_path, "requirements.txt", "Flask==3.0\n")
    services = detect.detect_services(tmp_path)
    assert len(services) == 1
    assert "flask run" in services[0].command
    assert services[0].port == 5000


def test_detects_go_and_rust(tmp_path):
    _write(tmp_path, "go.mod", "module example.com/app\n")
    svc = detect.detect_services(tmp_path)[0]
    assert svc.command == "go run ." and svc.auto_port is True

    _write(tmp_path, "Cargo.toml", "[package]\nname = \"app\"\n")
    # go.mod and Cargo.toml both yield name "app"; dedup keeps the first.
    names = [s.name for s in detect.detect_services(tmp_path)]
    assert names.count("app") == 1


def test_detects_procfile_entries(tmp_path):
    _write(tmp_path, "Procfile", "# comment\nweb: gunicorn app:app\nworker: celery -A app worker\n")
    services = detect.detect_services(tmp_path)
    assert sorted(s.name for s in services) == ["web", "worker"]
    assert all(s.auto_port for s in services)


def test_compose_long_form_published_port(tmp_path):
    _write(
        tmp_path,
        "compose.yaml",
        "services:\n  api:\n    image: app\n    ports:\n      - published: 8080\n        target: 80\n",
    )
    svc = detect.detect_services(tmp_path)[0]
    assert svc.name == "api" and svc.port == 8080


def test_node_generic_uses_start_script(tmp_path):
    _write(tmp_path, "package.json", json.dumps({"scripts": {"start": "node server.js"}}))
    svc = detect.detect_services(tmp_path)[0]
    assert svc.name == "web"
    assert svc.command == "npm run start"
    assert svc.port == 3000


def test_render_blank_template_is_valid_yaml(tmp_path):
    text = detect.render_manifest([])
    data = yaml.safe_load(text)
    assert "services" in data
