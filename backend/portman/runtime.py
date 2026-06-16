"""Runtime operations — the layer that ties persistence, supervision, scanning
and auditing together.

Holds the process-lifetime singletons (one supervisor, one scanner) and the
verbs the API exposes: register/start/stop/kill services, reserve and generate
ports, classify the live system, and tail logs.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit, config, ports
from .models import (
    AuditType,
    PortReservation,
    ReservationStatus,
    Run,
    RunStatus,
    Service,
)
from .scanner import Scanner
from .supervisor import LaunchSpec, Supervisor

supervisor = Supervisor()
scanner = Scanner()


class ServiceError(Exception):
    """Raised for invalid service operations (mapped to HTTP 400/404 in the API)."""


# --- serialization ----------------------------------------------------------


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def service_to_dict(session: Session, svc: Service) -> dict:
    running = supervisor.is_running(svc.id)
    info = supervisor.info(svc.id)
    latest = session.scalars(
        select(Run).where(Run.service_id == svc.id).order_by(Run.id.desc()).limit(1)
    ).first()
    return {
        "id": svc.id,
        "name": svc.name,
        "slug": svc.slug,
        "description": svc.description,
        "command": svc.command,
        "cwd": svc.cwd,
        "env": svc.env or {},
        "assigned_port": svc.assigned_port,
        "auto_restart": svc.auto_restart,
        "source": svc.source,
        "manifest_path": svc.manifest_path,
        "created_at": _iso(svc.created_at),
        "running": running,
        "pid": info.pid if (info and running) else None,
        "latest_run_id": latest.id if latest else None,
    }


def run_to_dict(run: Run) -> dict:
    return {
        "id": run.id,
        "service_id": run.service_id,
        "pid": run.pid,
        "status": run.status,
        "started_at": _iso(run.started_at),
        "stopped_at": _iso(run.stopped_at),
        "exit_code": run.exit_code,
        "log_path": run.log_path,
    }


def reservation_to_dict(res: PortReservation) -> dict:
    return {
        "id": res.id,
        "port": res.port,
        "purpose": res.purpose,
        "service_id": res.service_id,
        "status": res.status,
        "reserved_at": _iso(res.reserved_at),
    }


def audit_to_dict(event) -> dict:
    return {"id": event.id, "ts": _iso(event.ts), "type": event.type, "detail": event.detail}


# --- helpers ----------------------------------------------------------------


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "service"


def unique_slug(session: Session, name: str) -> str:
    base = slugify(name)
    slug = base
    n = 2
    while session.scalars(select(Service).where(Service.slug == slug)).first():
        slug = f"{base}-{n}"
        n += 1
    return slug


def get_service(session: Session, service_id: int) -> Service:
    svc = session.get(Service, service_id)
    if svc is None:
        raise ServiceError(f"service {service_id} not found")
    return svc


def list_services(session: Session) -> list[Service]:
    return list(session.scalars(select(Service).order_by(Service.name)))


def managed_ports(session: Session) -> dict[int, int]:
    """Assigned ports of services portman currently has running -> service id."""
    out: dict[int, int] = {}
    for svc in session.scalars(select(Service)):
        if svc.assigned_port and supervisor.is_running(svc.id):
            out[svc.assigned_port] = svc.id
    return out


def reserved_ports(session: Session) -> dict[int, int]:
    out: dict[int, int] = {}
    stmt = select(PortReservation).where(
        PortReservation.status == ReservationStatus.reserved.value
    )
    for res in session.scalars(stmt):
        out[res.port] = res.id
    return out


def used_ports(session: Session) -> set[int]:
    """Every port we should avoid handing out: managed, reserved, or listening."""
    used = set(managed_ports(session)) | set(reserved_ports(session))
    used |= {lp.port for lp in ports.list_listening()}
    return used


def _owner_purposes(name: str) -> set[str]:
    """Reservation purposes that count as belonging to a service named ``name``."""
    return {name, f"portman-init:{name}", f"service:{name}"}


def claim_port(
    session: Session,
    *,
    desired: int | None,
    auto: bool,
    owner_name: str,
    owner_service_id: int | None = None,
) -> tuple[int | None, int | None]:
    """Resolve the port a service should use, avoiding conflicts.

    Returns ``(port, reassigned_from)``. A fixed ``desired`` port that is already
    taken — listening, managed by another running service, or reserved for a
    different purpose — is reassigned to a free port, and ``reassigned_from``
    records the originally requested port. Ports the *owner* already holds (its
    current assignment, or a reservation made for it by ``portman init``) never
    count as conflicts, so re-importing is stable.
    """
    own: set[int] = set()
    if owner_service_id is not None:
        svc = session.get(Service, owner_service_id)
        if svc and svc.assigned_port:
            own.add(svc.assigned_port)

    purposes = _owner_purposes(owner_name)
    foreign_reserved: set[int] = set()
    stmt = select(PortReservation).where(
        PortReservation.status == ReservationStatus.reserved.value
    )
    for res in session.scalars(stmt):
        (own if res.purpose in purposes else foreign_reserved).add(res.port)

    taken = (
        set(managed_ports(session))
        | foreign_reserved
        | {lp.port for lp in ports.list_listening()}
    ) - own

    reassigned_from: int | None = None
    if desired is not None:
        if desired in taken:
            port = ports.find_free_port(exclude=taken)
            reassigned_from = desired
        else:
            port = desired
    elif auto:
        port = ports.find_free_port(exclude=taken)
    else:
        port = None
    return port, reassigned_from


def adopt_init_reservations(session: Session, owner_name: str) -> None:
    """Drop init-time reservations for a service now that it owns its port.

    ``portman init`` reserves a port with purpose ``portman-init:<name>``; once
    the service is actually registered it supersedes that placeholder, so we
    release it to keep the reservations list honest.
    """
    stmt = select(PortReservation).where(
        PortReservation.purpose == f"portman-init:{owner_name}"
    )
    for res in session.scalars(stmt):
        session.delete(res)


# --- service lifecycle ------------------------------------------------------


def create_service(session: Session, data) -> Service:
    port, reassigned_from = claim_port(
        session, desired=data.port, auto=data.auto_port, owner_name=data.name
    )
    svc = Service(
        name=data.name,
        slug=unique_slug(session, data.name),
        description=data.description,
        command=data.command,
        cwd=data.cwd,
        env=data.env or {},
        assigned_port=port,
        auto_restart=data.auto_restart,
        source="ui",
    )
    session.add(svc)
    session.flush()
    adopt_init_reservations(session, data.name)
    audit.record(
        session,
        AuditType.authorize.value,
        service=svc.slug,
        port=port,
        reassigned_from=reassigned_from,
        command=svc.command,
    )
    return svc


def delete_service(session: Session, service_id: int) -> None:
    svc = get_service(session, service_id)
    if supervisor.is_running(svc.id):
        raise ServiceError("stop the service before deleting it")
    session.delete(svc)


def start_service(session: Session, service_id: int) -> Run:
    svc = get_service(session, service_id)
    if supervisor.is_running(svc.id):
        raise ServiceError("service is already running")

    run = Run(service_id=svc.id, status=RunStatus.running.value)
    session.add(run)
    session.flush()

    env = dict(svc.env or {})
    if svc.assigned_port:
        env.setdefault("PORT", str(svc.assigned_port))
    # Encourage line-buffered output so live log tailing is responsive.
    env.setdefault("PYTHONUNBUFFERED", "1")
    spec = LaunchSpec(
        key=svc.id, run_id=run.id, slug=svc.slug, command=svc.command, cwd=svc.cwd, env=env
    )
    info = supervisor.start(spec)
    run.pid = info.pid
    run.log_path = info.log_path
    audit.record(
        session, AuditType.start.value, service=svc.slug, pid=info.pid, port=svc.assigned_port
    )
    return run


def _finalize_run(session: Session, svc: Service, returncode: int | None) -> None:
    run = session.scalars(
        select(Run)
        .where(Run.service_id == svc.id, Run.status == RunStatus.running.value)
        .order_by(Run.id.desc())
    ).first()
    if run is None:
        return
    run.stopped_at = datetime.now().astimezone()
    run.exit_code = returncode
    run.status = (
        RunStatus.crashed.value if returncode not in (0, None, -15) else RunStatus.stopped.value
    )


def stop_service(session: Session, service_id: int, *, force: bool = False) -> None:
    svc = get_service(session, service_id)
    info = supervisor.kill(svc.id) if force else supervisor.stop(svc.id)
    _finalize_run(session, svc, info.returncode if info else None)
    audit.record(
        session,
        (AuditType.kill if force else AuditType.stop).value,
        service=svc.slug,
    )


def restart_service(session: Session, service_id: int) -> Run:
    svc = get_service(session, service_id)
    if supervisor.is_running(svc.id):
        stop_service(session, service_id)
    audit.record(session, AuditType.restart.value, service=svc.slug)
    return start_service(session, service_id)


def list_runs(session: Session, service_id: int) -> list[Run]:
    return list(
        session.scalars(
            select(Run).where(Run.service_id == service_id).order_by(Run.id.desc())
        )
    )


# --- ports & reservations ---------------------------------------------------


def reserve_port(session: Session, data) -> PortReservation:
    port = data.port
    if port is None:
        if not data.auto:
            raise ServiceError("provide a port or set auto=true")
        port = ports.find_free_port(exclude=used_ports(session))
    # Idempotent: reserving an already-reserved port returns the existing row
    # instead of stacking duplicates (so re-running ``portman init`` is a no-op).
    existing = session.scalars(
        select(PortReservation).where(
            PortReservation.port == port,
            PortReservation.status == ReservationStatus.reserved.value,
        )
    ).first()
    if existing is not None:
        if data.purpose and not existing.purpose:
            existing.purpose = data.purpose
        return existing
    res = PortReservation(
        port=port, purpose=data.purpose, status=ReservationStatus.reserved.value
    )
    session.add(res)
    session.flush()
    audit.record(session, AuditType.reserve.value, port=port, purpose=data.purpose)
    return res


def list_reservations(session: Session) -> list[PortReservation]:
    return list(session.scalars(select(PortReservation).order_by(PortReservation.port)))


def release_reservation(session: Session, reservation_id: int) -> None:
    res = session.get(PortReservation, reservation_id)
    if res is None:
        raise ServiceError(f"reservation {reservation_id} not found")
    audit.record(session, AuditType.release.value, port=res.port)
    session.delete(res)


def generate_port(session: Session) -> int:
    return ports.find_free_port(exclude=used_ports(session))


def kill_port(session: Session, port: int) -> list[int]:
    killed = supervisor.kill_port(port)
    audit.record(session, AuditType.kill_port.value, port=port, pids=killed)
    return killed


# --- classification & logs --------------------------------------------------


def ports_view(session: Session) -> dict:
    managed = managed_ports(session)
    reserved = reserved_ports(session)
    classified = scanner.classify_now(managed, reserved)
    listening_ports = {c.port for c in classified}
    idle_reservations = [
        reservation_to_dict(r)
        for r in list_reservations(session)
        if r.port not in listening_ports
    ]
    counts = {
        "managed": sum(1 for c in classified if c.status == "managed"),
        "unauthorized": sum(1 for c in classified if c.status == "unauthorized"),
        "reserved_idle": len(idle_reservations),
    }
    return {
        "ports": [c.to_dict() for c in classified],
        "services": [service_to_dict(session, s) for s in list_services(session)],
        "reservations": [reservation_to_dict(r) for r in list_reservations(session)],
        "idle_reservations": idle_reservations,
        "counts": counts,
    }


def run_log_path(session: Session, run_id: int) -> str | None:
    run = session.get(Run, run_id)
    return run.log_path if run and run.log_path else None


# --- diagnostics -------------------------------------------------------------


def diagnose(session: Session) -> dict:
    """Report port conflicts portman can see across services, reservations and
    the live system. Returns ``{"daemon_port", "conflicts": [...], "ok": bool}``.
    """
    services = list_services(session)
    listening = {lp.port: lp for lp in ports.list_listening()}
    managed = managed_ports(session)
    conflicts: list[dict] = []

    # Two services configured on the same port — only one can ever bind it.
    by_port: dict[int, list[str]] = {}
    for svc in services:
        if svc.assigned_port:
            by_port.setdefault(svc.assigned_port, []).append(svc.name)
    for port, names in sorted(by_port.items()):
        if len(names) > 1:
            conflicts.append({
                "type": "duplicate_assignment",
                "port": port,
                "detail": f"services {', '.join(sorted(names))} all claim port {port}",
            })

    # A service's port is held by something that isn't its own managed run.
    for svc in services:
        port = svc.assigned_port
        if port and port in listening and not supervisor.is_running(svc.id):
            lp = listening[port]
            conflicts.append({
                "type": "port_taken",
                "port": port,
                "detail": (
                    f"port {port} for '{svc.name}' is held by "
                    f"{lp.cmdline or lp.name or 'an unknown process'} (pid {lp.pid})"
                ),
            })

    # A reserved port is occupied by a process that is not a managed service.
    for res in list_reservations(session):
        if res.port in listening and res.port not in managed:
            lp = listening[res.port]
            conflicts.append({
                "type": "reservation_taken",
                "port": res.port,
                "detail": (
                    f"reserved port {res.port} ({res.purpose or 'no purpose'}) is held by "
                    f"{lp.cmdline or lp.name or 'an unknown process'} (pid {lp.pid})"
                ),
            })

    return {"daemon_port": config.daemon_port(), "conflicts": conflicts, "ok": not conflicts}


# --- manifests --------------------------------------------------------------


def import_manifest(session: Session, path: str) -> dict:
    """Import a project's portman.yaml (raises ServiceError on a bad manifest)."""
    from .manifest import ManifestError, import_manifest as _import

    try:
        return _import(session, path)
    except ManifestError as exc:
        raise ServiceError(str(exc)) from exc


# --- background scan loop ----------------------------------------------------


async def scan_loop(interval: float | None = None) -> None:
    """Periodically reconcile the system and audit-log new unauthorized ports."""
    from .db import session_scope

    delay = interval or config.SCAN_INTERVAL_SECONDS
    while True:
        try:
            with session_scope() as session:
                managed = managed_ports(session)
                reserved = reserved_ports(session)
                classified = scanner.classify_now(managed, reserved)
                scanner.flag_new(session, classified)
        except Exception:  # pragma: no cover - the loop must never die
            pass
        await asyncio.sleep(delay)
