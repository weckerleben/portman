"""ASGI application: wires the API, serves the built SPA, and runs the scanner."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, db, runtime
from .api import router

# frontend/dist relative to the repo root (backend/portman/app.py -> ../../frontend/dist)
SPA_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    scan_task = asyncio.create_task(runtime.scan_loop())
    try:
        yield
    finally:
        scan_task.cancel()


def create_app() -> FastAPI:
    app = FastAPI(title="portman", version=__version__, lifespan=lifespan)
    app.include_router(router)

    @app.exception_handler(runtime.ServiceError)
    async def _service_error_handler(_: Request, exc: runtime.ServiceError):
        status = 404 if "not found" in str(exc) else 400
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    # Serve the built SPA last so explicit /api and /ws routes win. html=True
    # makes client-side routes fall back to index.html.
    if SPA_DIR.exists():
        app.mount("/", StaticFiles(directory=str(SPA_DIR), html=True), name="spa")

    return app


app = create_app()
