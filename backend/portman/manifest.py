"""Per-project manifests.

A project may declare its services in a ``portman.yaml`` at its root. Importing
that file registers (or updates) those services so a project's port assignments
are reproducible and version-controlled, rather than re-entered by hand.

Schema::

    services:
      - name: web
        command: "npm run dev"
        cwd: .                 # optional, relative to the manifest; defaults to manifest dir
        port: auto             # a number, or "auto" for a generated free port
        description: "Next.js dev server"
        auto_restart: false    # optional
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit, ports
from .models import AuditType, Service

MANIFEST_NAME = "portman.yaml"


class ManifestError(Exception):
    """Raised when a manifest is missing or malformed."""


@dataclass
class ManifestService:
    name: str
    command: str
    description: str = ""
    cwd: str = ""
    port: int | None = None
    auto_port: bool = False
    auto_restart: bool = False


def resolve_path(path: str) -> Path:
    """Accept either a directory (look for portman.yaml inside) or the file itself."""
    p = Path(path).expanduser()
    if p.is_dir():
        p = p / MANIFEST_NAME
    if not p.exists():
        raise ManifestError(f"No manifest found at {p}")
    return p


def parse(path: str) -> tuple[list[ManifestService], Path]:
    manifest_path = resolve_path(path)
    base = manifest_path.parent
    try:
        raw = yaml.safe_load(manifest_path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ManifestError(f"Invalid YAML in {manifest_path}: {exc}") from exc

    entries = raw.get("services")
    if not isinstance(entries, list) or not entries:
        raise ManifestError("Manifest must contain a non-empty 'services' list")

    services: list[ManifestService] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ManifestError(f"services[{i}] must be a mapping")
        name = entry.get("name")
        command = entry.get("command")
        if not name or not command:
            raise ManifestError(f"services[{i}] requires both 'name' and 'command'")

        port_value = entry.get("port")
        auto_port = str(port_value).lower() == "auto"
        port = None if (port_value is None or auto_port) else int(port_value)

        cwd = entry.get("cwd", "")
        resolved_cwd = str((base / cwd).resolve()) if cwd else str(base)

        services.append(
            ManifestService(
                name=str(name),
                command=str(command),
                description=str(entry.get("description", "")),
                cwd=resolved_cwd,
                port=port,
                auto_port=auto_port,
                auto_restart=bool(entry.get("auto_restart", False)),
            )
        )
    return services, manifest_path


def import_manifest(session: Session, path: str) -> dict:
    """Register or update every service declared in a project's manifest.

    Matching is by service name: an existing service with the same name is
    updated in place (so re-importing after an edit is idempotent).
    """
    from .runtime import unique_slug, used_ports  # local import to avoid a cycle

    services, manifest_path = parse(path)
    created, updated = [], []

    for ms in services:
        existing = session.scalars(select(Service).where(Service.name == ms.name)).first()
        port = ms.port
        if port is None and ms.auto_port:
            port = ports.find_free_port(exclude=used_ports(session))

        if existing is None:
            svc = Service(
                name=ms.name,
                slug=unique_slug(session, ms.name),
                description=ms.description,
                command=ms.command,
                cwd=ms.cwd,
                assigned_port=port,
                auto_restart=ms.auto_restart,
                source="manifest",
                manifest_path=str(manifest_path),
            )
            session.add(svc)
            created.append(ms.name)
        else:
            existing.description = ms.description
            existing.command = ms.command
            existing.cwd = ms.cwd
            if ms.port is not None or ms.auto_port:
                existing.assigned_port = port
            existing.auto_restart = ms.auto_restart
            existing.source = "manifest"
            existing.manifest_path = str(manifest_path)
            updated.append(ms.name)

    audit.record(
        session,
        AuditType.authorize.value,
        manifest=str(manifest_path),
        created=created,
        updated=updated,
    )
    return {"manifest": str(manifest_path), "created": created, "updated": updated}
