"""HTTP + WebSocket API surface."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from . import audit, runtime
from .db import session_scope
from .schemas import ReservationIn, ServiceIn

router = APIRouter()


def get_session() -> Iterator[Session]:
    with session_scope() as session:
        yield session


def _raise_service_error(exc: "runtime.ServiceError") -> None:
    status = 404 if "not found" in str(exc) else 400
    raise HTTPException(status_code=status, detail=str(exc)) from exc


def _service_or_404(session: Session, service_id: int) -> None:
    try:
        runtime.get_service(session, service_id)
    except runtime.ServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# --- health & live system ---------------------------------------------------


@router.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/api/ports")
def get_ports(session: Session = Depends(get_session)) -> dict:
    return runtime.ports_view(session)


# --- services ---------------------------------------------------------------


@router.get("/api/services")
def list_services(session: Session = Depends(get_session)) -> list[dict]:
    return [runtime.service_to_dict(session, s) for s in runtime.list_services(session)]


@router.post("/api/services", status_code=201)
def create_service(payload: ServiceIn, session: Session = Depends(get_session)) -> dict:
    try:
        svc = runtime.create_service(session, payload)
    except RuntimeError as exc:  # no free port
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.flush()
    return runtime.service_to_dict(session, svc)


@router.get("/api/services/{service_id}")
def get_service(service_id: int, session: Session = Depends(get_session)) -> dict:
    _service_or_404(session, service_id)
    svc = runtime.get_service(session, service_id)
    data = runtime.service_to_dict(session, svc)
    data["runs"] = [runtime.run_to_dict(r) for r in runtime.list_runs(session, service_id)]
    return data


@router.delete("/api/services/{service_id}", status_code=204)
def delete_service(service_id: int, session: Session = Depends(get_session)) -> None:
    try:
        runtime.delete_service(session, service_id)
    except runtime.ServiceError as exc:
        _raise_service_error(exc)


@router.post("/api/services/{service_id}/start")
def start_service(service_id: int, session: Session = Depends(get_session)) -> dict:
    try:
        run = runtime.start_service(session, service_id)
    except runtime.ServiceError as exc:
        _raise_service_error(exc)
    return runtime.run_to_dict(run)


@router.post("/api/services/{service_id}/stop")
def stop_service(service_id: int, session: Session = Depends(get_session)) -> dict:
    try:
        runtime.stop_service(session, service_id)
    except runtime.ServiceError as exc:
        _raise_service_error(exc)
    return {"status": "stopped"}


@router.post("/api/services/{service_id}/kill")
def kill_service(service_id: int, session: Session = Depends(get_session)) -> dict:
    try:
        runtime.stop_service(session, service_id, force=True)
    except runtime.ServiceError as exc:
        _raise_service_error(exc)
    return {"status": "killed"}


@router.post("/api/services/{service_id}/restart")
def restart_service(service_id: int, session: Session = Depends(get_session)) -> dict:
    try:
        run = runtime.restart_service(session, service_id)
    except runtime.ServiceError as exc:
        _raise_service_error(exc)
    return runtime.run_to_dict(run)


@router.get("/api/services/{service_id}/runs")
def list_service_runs(service_id: int, session: Session = Depends(get_session)) -> list[dict]:
    _service_or_404(session, service_id)
    return [runtime.run_to_dict(r) for r in runtime.list_runs(session, service_id)]


# --- runs & logs ------------------------------------------------------------


@router.get("/api/runs/{run_id}/log")
def get_run_log(run_id: int, tail: int = 500, session: Session = Depends(get_session)) -> dict:
    path = runtime.run_log_path(session, run_id)
    if not path or not Path(path).exists():
        return {"run_id": run_id, "lines": []}
    lines = Path(path).read_text(errors="replace").splitlines()
    return {"run_id": run_id, "lines": lines[-tail:]}


# --- ports: kill / generate -------------------------------------------------


@router.post("/api/ports/{port}/kill")
def kill_port(port: int, session: Session = Depends(get_session)) -> dict:
    killed = runtime.kill_port(session, port)
    return {"port": port, "killed_pids": killed}


@router.post("/api/ports/generate")
def generate_port(session: Session = Depends(get_session)) -> dict:
    try:
        return {"port": runtime.generate_port(session)}
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# --- reservations -----------------------------------------------------------


@router.get("/api/reservations")
def list_reservations(session: Session = Depends(get_session)) -> list[dict]:
    return [runtime.reservation_to_dict(r) for r in runtime.list_reservations(session)]


@router.post("/api/reservations", status_code=201)
def create_reservation(payload: ReservationIn, session: Session = Depends(get_session)) -> dict:
    try:
        res = runtime.reserve_port(session, payload)
    except runtime.ServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return runtime.reservation_to_dict(res)


@router.delete("/api/reservations/{reservation_id}", status_code=204)
def delete_reservation(reservation_id: int, session: Session = Depends(get_session)) -> None:
    try:
        runtime.release_reservation(session, reservation_id)
    except runtime.ServiceError as exc:
        _raise_service_error(exc)


# --- audit ------------------------------------------------------------------


@router.get("/api/audit")
def list_audit(limit: int = 200, session: Session = Depends(get_session)) -> list[dict]:
    return [runtime.audit_to_dict(e) for e in audit.list_events(session, limit=limit)]


# --- websockets -------------------------------------------------------------


@router.websocket("/ws/status")
async def ws_status(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            with session_scope() as session:
                view = runtime.ports_view(session)
            await websocket.send_json(view)
            await asyncio.sleep(2.0)
    except WebSocketDisconnect:
        return


@router.websocket("/ws/logs/{run_id}")
async def ws_logs(websocket: WebSocket, run_id: int) -> None:
    await websocket.accept()
    with session_scope() as session:
        path = runtime.run_log_path(session, run_id)
    if not path or not Path(path).exists():
        await websocket.send_json({"error": "log not found"})
        await websocket.close()
        return
    try:
        with open(path, "r", errors="replace") as handle:
            backlog = handle.read()
            if backlog:
                await websocket.send_json({"chunk": backlog})
            while True:
                chunk = handle.read()
                if chunk:
                    await websocket.send_json({"chunk": chunk})
                else:
                    await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return
