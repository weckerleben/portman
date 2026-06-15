"""Static project detection for ``portman init``.

Heuristics that read a project's manifest files (package.json, pyproject.toml,
docker-compose.yml, …) and infer the services it likely runs, so ``init`` can
write a ready-to-edit ``portman.yaml``. This is deliberately separate from
:mod:`portman.scanner`, which inspects *live* listeners; here nothing runs — we
only read files on disk.

Every detector returns :class:`DetectedService` objects carrying a ``note`` that
explains *why* they were detected; ``init`` renders those notes as comments.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

# Common Node web frameworks → (default dev port, extra dev flags).
_NODE_FRAMEWORKS = {
    "vite": (5173, "-- --port $PORT"),
    "next": (3000, "-- -p $PORT"),
    "react-scripts": (3000, ""),  # CRA reads the PORT env var portman injects
    "@angular/cli": (4200, "-- --port $PORT"),
    "nuxt": (3000, "-- --port $PORT"),
}

# Subdirectories worth probing for a nested Node app in a monorepo layout.
_NODE_SUBDIRS = ("frontend", "client", "web", "app", "ui")

# Subdirectories worth probing for a nested Python backend in a monorepo layout.
_PYTHON_SUBDIRS = ("backend", "api", "server", "app", "src")


@dataclass(frozen=True)
class DetectedService:
    """One inferred service, plus the rationale for the comment in the YAML."""

    name: str
    command: str
    description: str = ""
    cwd: str = ""  # relative to the project root; "" means the root itself
    port: int | None = None
    auto_port: bool = False
    auto_restart: bool = False
    note: str = ""


def detect_services(root: Path) -> list[DetectedService]:
    """Run every detector over ``root`` and return de-duplicated services."""
    root = Path(root)
    found: list[DetectedService] = []
    for detector in (_detect_node, _detect_python, _detect_compose, _detect_go, _detect_rust, _detect_procfile):
        found.extend(detector(root))

    seen: set[str] = set()
    unique: list[DetectedService] = []
    for svc in found:
        if svc.name in seen:
            continue
        seen.add(svc.name)
        unique.append(svc)
    return unique


# --- detectors --------------------------------------------------------------


def _detect_node(root: Path) -> list[DetectedService]:
    candidates = [root, *(root / sub for sub in _NODE_SUBDIRS)]
    services: list[DetectedService] = []
    for directory in candidates:
        manifest = directory / "package.json"
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        scripts = data.get("scripts") or {}
        script = "dev" if "dev" in scripts else ("start" if "start" in scripts else None)
        if script is None:
            continue

        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        port, flag, framework = 3000, "", "Node"
        for marker, (fw_port, fw_flag) in _NODE_FRAMEWORKS.items():
            if marker in deps:
                port, flag, framework = fw_port, fw_flag, marker
                break

        rel = "" if directory == root else directory.name
        command = f"npm run {script}{(' ' + flag) if flag else ''}".strip()
        services.append(
            DetectedService(
                name=rel or "web",
                command=command,
                description=f"{framework} dev server",
                cwd=rel,
                port=port,
                note=f"package.json with {framework} (script: {script})",
            )
        )
    return services


def _detect_python(root: Path) -> list[DetectedService]:
    services: list[DetectedService] = []
    for directory in (root, *(root / sub for sub in _PYTHON_SUBDIRS)):
        if directory != root and not directory.is_dir():
            continue
        svc = _detect_python_dir(root, directory)
        if svc is not None:
            services.append(svc)
    return services


def _detect_python_dir(root: Path, directory: Path) -> DetectedService | None:
    rel = "" if directory == root else directory.name

    if (directory / "manage.py").is_file():
        return DetectedService(
            name=rel or "web",
            command="python manage.py runserver $PORT",
            description="Django dev server",
            cwd=rel,
            port=8000,
            note="manage.py (Django)",
        )

    text = ""
    for name in ("pyproject.toml", "requirements.txt"):
        candidate = directory / name
        if candidate.is_file():
            text += candidate.read_text().lower()
    if not text:
        return None

    if "fastapi" in text or "uvicorn" in text:
        return DetectedService(
            name=rel or "api",
            command="uvicorn app:app --host 127.0.0.1 --port $PORT",
            description="FastAPI app (adjust the module path)",
            cwd=rel,
            auto_port=True,
            note="pyproject/requirements with fastapi/uvicorn",
        )
    if "flask" in text:
        return DetectedService(
            name=rel or "web",
            command="flask run --port $PORT",
            description="Flask app",
            cwd=rel,
            port=5000,
            note="pyproject/requirements with flask",
        )
    return None


def _detect_compose(root: Path) -> list[DetectedService]:
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        path = root / name
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError:
            return []
        services: list[DetectedService] = []
        for svc_name, spec in (data.get("services") or {}).items():
            if not isinstance(spec, dict):
                continue
            host_port = _first_host_port(spec.get("ports") or [])
            services.append(
                DetectedService(
                    name=str(svc_name),
                    command=f"docker compose up {svc_name}",
                    description=f"compose service ({spec.get('image', 'build')})",
                    port=host_port,
                    auto_port=host_port is None,
                    note=f"{name} service",
                )
            )
        return services
    return []


def _first_host_port(ports: list) -> int | None:
    for entry in ports:
        if isinstance(entry, dict):  # long form: {published: 8080, target: 80}
            published = entry.get("published")
            if published is not None:
                return int(published)
            continue
        text = str(entry)
        host = text.split(":")[0] if ":" in text else text
        try:
            return int(host)
        except ValueError:
            continue
    return None


def _detect_go(root: Path) -> list[DetectedService]:
    if not (root / "go.mod").is_file():
        return []
    return [
        DetectedService(
            name="app",
            command="go run .",
            description="Go service (ensure it reads $PORT)",
            auto_port=True,
            note="go.mod",
        )
    ]


def _detect_rust(root: Path) -> list[DetectedService]:
    if not (root / "Cargo.toml").is_file():
        return []
    return [
        DetectedService(
            name="app",
            command="cargo run",
            description="Rust service (ensure it reads $PORT)",
            auto_port=True,
            note="Cargo.toml",
        )
    ]


def _detect_procfile(root: Path) -> list[DetectedService]:
    path = root / "Procfile"
    if not path.is_file():
        return []
    services: list[DetectedService] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        name, command = line.split(":", 1)
        name, command = name.strip(), command.strip()
        if not name or not command:
            continue
        services.append(
            DetectedService(
                name=name,
                command=command,
                description="Procfile entry",
                auto_port=True,
                note="Procfile",
            )
        )
    return services


# --- rendering --------------------------------------------------------------

_HEADER = """\
# portman.yaml — generated by `portman init`.
# Review the services below, adjust commands/ports, then register them with:
#     portman import
#
# Fields:
#   name         required — unique service name (re-import matches on this)
#   command      required — shell command; $PORT is injected when a port is set
#   cwd          optional — relative to this file; defaults to its directory
#   port         a number, or "auto" to generate a free port
#   description  optional — what the service does
#   auto_restart optional — reserved for a future watchdog
"""

_BLANK_EXAMPLE = """\
services:
  # Nothing was auto-detected. Replace this example with your real services.
  - name: web
    command: "npm run dev -- --port $PORT"
    cwd: .
    port: auto
    description: "your dev server"
"""


def render_manifest(services: list[DetectedService]) -> str:
    """Render services as commented YAML compatible with :mod:`portman.manifest`."""
    if not services:
        return f"{_HEADER}\n{_BLANK_EXAMPLE}"

    lines = [_HEADER, "services:"]
    for svc in services:
        if svc.note:
            lines.append(f"  # {svc.note}")
        lines.append(f"  - name: {svc.name}")
        lines.append(f'    command: "{_yaml_escape(svc.command)}"')
        if svc.cwd:
            lines.append(f"    cwd: {svc.cwd}")
        if svc.auto_port:
            lines.append("    port: auto")
        elif svc.port is not None:
            lines.append(f"    port: {svc.port}")
        if svc.description:
            lines.append(f'    description: "{_yaml_escape(svc.description)}"')
        if svc.auto_restart:
            lines.append("    auto_restart: true")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _yaml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
