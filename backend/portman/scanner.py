"""Reconciliation scanner.

Compares what is *actually* listening (from :mod:`portman.ports`) against what
portman manages and reserves, classifying every live port as ``managed`` or
``unauthorized``. Newly appearing unauthorized ports are written to the audit log.

Port-based matching (not PID-based) is intentional: services are launched through
a shell, so the listening socket usually belongs to a child PID, but the *port* is
the assigned port portman knows about.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable, Iterable

from sqlalchemy.orm import Session

from . import audit
from .models import AuditType
from .ports import ListeningPort, list_listening

MANAGED = "managed"
UNAUTHORIZED = "unauthorized"


@dataclass(frozen=True)
class ClassifiedPort:
    port: int
    pid: int | None
    name: str
    cmdline: str
    cwd: str
    status: str  # MANAGED | UNAUTHORIZED
    service_id: int | None = None
    reservation_id: int | None = None  # set when an unauthorized port squats a reservation

    def to_dict(self) -> dict:
        return asdict(self)


def classify(
    listening: Iterable[ListeningPort],
    managed: dict[int, int],
    reserved: dict[int, int] | None = None,
) -> list[ClassifiedPort]:
    """Classify each listening port.

    ``managed`` maps an assigned port -> service id (services portman has
    running). ``reserved`` maps a held port -> reservation id; a process bound to
    a reserved port that portman did not launch is still *unauthorized*, but we
    note the reservation it is squatting.
    """
    reserved = reserved or {}
    result: list[ClassifiedPort] = []
    for lp in listening:
        if lp.port in managed:
            result.append(
                ClassifiedPort(
                    port=lp.port,
                    pid=lp.pid,
                    name=lp.name,
                    cmdline=lp.cmdline,
                    cwd=lp.cwd,
                    status=MANAGED,
                    service_id=managed[lp.port],
                )
            )
        else:
            result.append(
                ClassifiedPort(
                    port=lp.port,
                    pid=lp.pid,
                    name=lp.name,
                    cmdline=lp.cmdline,
                    cwd=lp.cwd,
                    status=UNAUTHORIZED,
                    reservation_id=reserved.get(lp.port),
                )
            )
    result.sort(key=lambda c: c.port)
    return result


def unauthorized_ports(classified: Iterable[ClassifiedPort]) -> list[ClassifiedPort]:
    return [c for c in classified if c.status == UNAUTHORIZED]


def new_unauthorized(
    classified: Iterable[ClassifiedPort], seen: set[int]
) -> list[ClassifiedPort]:
    """Unauthorized ports not present in the ``seen`` set."""
    return [c for c in unauthorized_ports(classified) if c.port not in seen]


class Scanner:
    """Stateful reconciler that remembers which unauthorized ports it has flagged."""

    def __init__(self, lister: Callable[[], list[ListeningPort]] = list_listening):
        self._lister = lister
        self._seen_unauthorized: set[int] = set()

    def classify_now(
        self, managed: dict[int, int], reserved: dict[int, int] | None = None
    ) -> list[ClassifiedPort]:
        return classify(self._lister(), managed, reserved)

    def flag_new(self, session: Session, classified: Iterable[ClassifiedPort]) -> list[ClassifiedPort]:
        """Audit-log unauthorized ports that have appeared since the last scan."""
        classified = list(classified)
        fresh = new_unauthorized(classified, self._seen_unauthorized)
        for port in fresh:
            audit.record(
                session,
                AuditType.flag_unauthorized.value,
                port=port.port,
                pid=port.pid,
                name=port.name,
                cmdline=port.cmdline,
            )
        self._seen_unauthorized = {c.port for c in unauthorized_ports(classified)}
        return fresh
