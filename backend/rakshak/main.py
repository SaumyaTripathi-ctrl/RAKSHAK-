"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api.routes import core, devices, events, shipments
from .config import Settings, get_settings
from .db.base import Database
from .services.ingest import Ingestor
from .services.mqtt import MqttBridge, NullPublisher
from .services.realtime import RealtimeHub

log = logging.getLogger("rakshak")


def create_app(settings: Settings | None = None, *, db: Database | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=False,
    )
    database = db or Database(settings.database_url)
    realtime = RealtimeHub()
    ingestor = Ingestor(database, settings, realtime)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.auto_create_schema:
            await (
                database.create_all()
            )  # dev/tests; production schema comes from `alembic upgrade head`
        if settings.using_dev_secrets and settings.env != "dev":
            raise RuntimeError(
                "refusing to start: dev master key / JWT secret outside RAKSHAK_ENV=dev"
            )
        if settings.seed_demo:
            from .seed import seed_demo

            await seed_demo(database, settings)
        for hook in app.state.startup_hooks:
            await hook(app)
        if isinstance(app.state.publisher, MqttBridge):
            app.state.publisher.start()
        log.info(
            "Rakshak API %s started (mqtt=%s, ledger=%s)",
            __version__,
            settings.mqtt_enabled,
            settings.ledger_backend,
        )
        try:
            yield
        finally:
            for hook in app.state.shutdown_hooks:
                await hook(app)
            if isinstance(app.state.publisher, MqttBridge):
                await app.state.publisher.stop()
            await database.dispose()

    app = FastAPI(
        title="Rakshak API",
        version=__version__,
        description="Farm-to-fork traceability backend (SIH26232). Simulated data is labelled as such.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.db = database
    app.state.realtime = realtime
    app.state.ingestor = ingestor
    app.state.startup_hooks = []
    app.state.shutdown_hooks = []
    app.state.bridge = None
    app.state.publisher = NullPublisher()
    if settings.mqtt_enabled:
        bridge = MqttBridge(settings, ingestor)
        app.state.bridge = bridge
        app.state.publisher = bridge

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for r in (core.router, shipments.router, devices.router, events.router):
        app.include_router(r)

    from .extensions import install_extensions

    install_extensions(app)  # ledger / ml / simulator routes are added in later phases
    return app
