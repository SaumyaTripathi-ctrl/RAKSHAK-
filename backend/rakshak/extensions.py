"""Optional subsystems (ledger, prediction, simulator control) plug into the app here."""

from __future__ import annotations

import logging

from fastapi import FastAPI

from .api.routes import demo as demo_routes
from .api.routes import ledger as ledger_routes
from .api.routes import prediction as prediction_routes
from .api.routes import simulator as simulator_routes
from .ledger.anchor import Anchorer
from .ledger.client import make_ledger
from .ledger.verify import Verifier

log = logging.getLogger("rakshak")


def install_extensions(app: FastAPI) -> None:
    settings = app.state.settings
    ledger = make_ledger(
        settings.ledger_backend, path=settings.ledger_path, bridge_url=settings.fabric_bridge_url
    )
    app.state.ledger = ledger
    app.state.anchorer = Anchorer(app.state.db, settings, ledger, app.state.realtime)
    app.state.verifier = Verifier(app.state.db, ledger)
    app.state.ingestor.add_listener(app.state.anchorer.on_ingest)
    app.include_router(ledger_routes.router)

    app.include_router(demo_routes.router)
    app.include_router(simulator_routes.router)
    app.state.simulator_client = None
    if settings.simulator_url:
        import httpx

        headers = {"X-Sim-Token": settings.simulator_token} if settings.simulator_token else {}
        app.state.simulator_client = httpx.AsyncClient(
            base_url=settings.simulator_url.rstrip("/"), headers=headers, timeout=15
        )

        async def close_sim(_app: FastAPI) -> None:
            await app.state.simulator_client.aclose()

        app.state.shutdown_hooks.append(close_sim)

    app.state.predictor = None
    app.state.facilities = []
    app.include_router(prediction_routes.router)
    if settings.predictions_enabled:
        _install_prediction(app)


def _install_prediction(app: FastAPI) -> None:
    from .prediction.facilities import load_facilities
    from .prediction.routing import Router
    from .prediction.service import ModelRegistry, PredictionService, resolve_model_dir
    from .prediction.weather import WeatherClient

    settings = app.state.settings
    registry = ModelRegistry(resolve_model_dir(settings))
    app.state.facilities = load_facilities(settings.facilities_csv)
    if not registry.loaded_profiles():
        log.warning(
            "no trained models in %s: prediction disabled (run `python -m rakshak_ml.train`)",
            registry.dir,
        )
        return
    service = PredictionService(
        app,
        app.state.db,
        settings,
        app.state.realtime,
        registry,
        Router(settings.osrm_url, enabled=settings.osrm_enabled),
        WeatherClient(enabled=settings.weather_enabled),
        app.state.facilities,
    )
    app.state.predictor = service
    app.state.ingestor.add_listener(service.on_ingest)

    async def close(_app: FastAPI) -> None:
        await service.aclose()

    app.state.shutdown_hooks.append(close)
