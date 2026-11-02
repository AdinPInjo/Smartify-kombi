"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from smartify import __version__
from smartify.api import auth, relays, sensors, system, wifi
from smartify.config import Settings, get_settings
from smartify.context import AppContext
from smartify.db import migrate
from smartify.hardware import Hardware, build_hardware
from smartify.logbuffer import LogBuffer
from smartify.services.relays import Conflict
from smartify.services.rules import NotFound

log = logging.getLogger(__name__)

SESSION_MAX_AGE = 30 * 24 * 3600


def create_app(
    settings: Settings | None = None,
    hardware: Hardware | None = None,
    start_workers: bool = True,
) -> FastAPI:
    """Build the app. Tests pass their own settings, mock hardware, and no workers."""
    settings = settings or get_settings()
    logs = LogBuffer()
    logging.getLogger().addHandler(logs)
    logging.getLogger("smartify").setLevel(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.uses_default_credentials:
            log.warning(
                "Default password or secret key in use. "
                "Set SMARTIFY_PASSWORD and SMARTIFY_SECRET_KEY before exposing the dashboard."
            )
        version = migrate(settings.db_path)
        log.info("Database %s at schema version %d", settings.db_path, version)
        ctx = AppContext.build(settings, hardware or build_hardware(settings), logs)
        app.state.ctx = ctx
        if start_workers:
            ctx.start()
        else:
            ctx.relays.startup()
        try:
            yield
        finally:
            ctx.stop()
            logging.getLogger().removeHandler(logs)

    app = FastAPI(title="Smartify Kombi", version=__version__, lifespan=lifespan)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="smartify_session",
        max_age=SESSION_MAX_AGE,
        same_site="lax",
    )

    @app.exception_handler(NotFound)
    async def _not_found(_: Request, exc: NotFound) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(Conflict)
    async def _conflict(_: Request, exc: Conflict) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ValueError)
    async def _invalid(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    for router in (system.router, auth.router, relays.router, sensors.router, wifi.router):
        app.include_router(router, prefix="/api")

    _mount_frontend(app, settings)
    return app


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    """Serve the built dashboard, with client-side routes falling back to index.html."""
    dist = settings.frontend_dir
    if dist is None or not (dist / "index.html").is_file():
        if dist is not None:
            log.warning("Frontend not found in %s, serving the API only", dist)
        return
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> Response:
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(root / "index.html", headers={"Cache-Control": "no-store"})
