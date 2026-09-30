"""Optional subsystems (ledger, prediction, simulator control) plug into the app here."""

from __future__ import annotations

from fastapi import FastAPI


def install_extensions(app: FastAPI) -> None:
    """Phase 3+ register ``app.state.verifier`` / ``anchorer`` / ``predictor`` and their routers."""
