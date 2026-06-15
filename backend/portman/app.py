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

def resolve_spa_dir(package_dir: Path, repo_root: Path) -> Path | None:
    """Locate the built SPA, preferring the copy bundled inside the package.

    Installed builds (pip/pipx/uv/brew) carry the SPA at ``portman/web``; a dev
    checkout serves it straight from ``frontend/dist``. Returns None if neither
    exists, in which case only the API is served.
    """
    packaged = package_dir / "web"
    if packaged.is_dir():
        return packaged
    repo_dist = repo_root / "frontend" / "dist"
    if repo_dist.is_dir():
        return repo_dist
    return None


# Packaged location first (portman/web), else the repo's frontend/dist for dev.
SPA_DIR = resolve_spa_dir(Path(__file__).resolve().parent, Path(__file__).resolve().parents[2])


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
    if SPA_DIR is not None:
        app.mount("/", StaticFiles(directory=str(SPA_DIR), html=True), name="spa")

    return app


app = create_app()
