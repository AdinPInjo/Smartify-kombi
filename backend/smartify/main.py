"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from smartify import __version__
from smartify.api import health
from smartify.config import Settings, get_settings
from smartify.db import migrate
from smartify.hardware import Hardware, build_hardware

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, hardware: Hardware | None = None) -> FastAPI:
    """Build the app. Tests pass their own settings and (mock) hardware."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.uses_default_credentials:
            log.warning(
                "Default password or secret key in use. "
                "Set SMARTIFY_PASSWORD and SMARTIFY_SECRET_KEY before exposing the dashboard."
            )
        version = migrate(settings.db_path)
        log.info("Database %s at schema version %d", settings.db_path, version)
        app.state.hardware = hardware or build_hardware(settings)
        yield
        gps = app.state.hardware.gps
        if gps is not None:
            gps.close()

    app = FastAPI(title="Smartify Kombi", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.include_router(health.router, prefix="/api")
    return app
