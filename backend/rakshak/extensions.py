"""Optional subsystems (ledger, prediction, simulator control) plug into the app here."""

from __future__ import annotations

from fastapi import FastAPI

from .api.routes import ledger as ledger_routes
from .ledger.anchor import Anchorer
from .ledger.client import make_ledger
from .ledger.verify import Verifier


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
