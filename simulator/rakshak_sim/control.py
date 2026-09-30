"""HTTP control surface of the simulator (the backend proxies it for the admin UI)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from .manager import RunManager
from .runner import INJECTIONS
from .scenarios import SCENARIOS


class StartBody(BaseModel):
    scenario: str
    hub_id: str | None = None
    food_type: str | None = None
    profile: str | None = Field(default=None, pattern="^(real|demo)$")
    accel: float | None = Field(default=None, gt=0, le=100000)
    seed: int = 1
    new_shipment: bool = False


class InjectBody(BaseModel):
    action: str
    params: dict = Field(default_factory=dict)


def create_control_app(manager: RunManager, token: str | None = None) -> FastAPI:
    app = FastAPI(title="Rakshak device simulator (SIMULATED devices)", version="0.1.0")
    app.state.manager = manager

    def auth(x_sim_token: Annotated[str | None, Header()] = None) -> None:
        if token and x_sim_token != token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad simulator token")

    Guard = Depends(auth)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "simulated": True, "runs": len(manager.runs)}

    @app.get("/scenarios", dependencies=[Guard])
    async def scenarios() -> dict:
        return {
            "scenarios": [
                {
                    "name": s.name,
                    "title": s.title,
                    "description": s.description,
                    "food_type": s.food_type,
                    "duration_min": s.duration_min,
                    "profile": s.profile,
                    "accel": s.accel,
                    "steps": [
                        {"at": st.at, "action": st.action, "params": st.params} for st in s.steps
                    ],
                }
                for s in SCENARIOS.values()
            ],
            "injections": list(INJECTIONS),
        }

    @app.get("/state", dependencies=[Guard])
    async def state() -> dict:
        return manager.status()

    @app.post("/runs", dependencies=[Guard], status_code=status.HTTP_201_CREATED)
    async def start(body: StartBody) -> dict:
        try:
            run = await manager.start(
                body.scenario,
                hub_id=body.hub_id,
                food_type=body.food_type,
                profile=body.profile,
                accel=body.accel,
                seed=body.seed,
                new_shipment=body.new_shipment,
            )
        except KeyError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        return run.status()

    def _run(run_id: str):
        run = manager.runs.get(run_id)
        if run is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown run")
        return run

    @app.get("/runs/{run_id}", dependencies=[Guard])
    async def get_run(run_id: str) -> dict:
        return _run(run_id).status()

    @app.post("/runs/{run_id}/inject", dependencies=[Guard])
    async def inject(run_id: str, body: InjectBody) -> dict:
        run = _run(run_id)
        if run.state not in ("running", "paused"):
            raise HTTPException(status.HTTP_409_CONFLICT, f"run is {run.state}")
        try:
            await run.apply(body.action, body.params)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        return run.status()

    @app.post("/runs/{run_id}/pause", dependencies=[Guard])
    async def pause(run_id: str) -> dict:
        run = _run(run_id)
        run.pause(True)
        return run.status()

    @app.post("/runs/{run_id}/resume", dependencies=[Guard])
    async def resume(run_id: str) -> dict:
        run = _run(run_id)
        run.pause(False)
        return run.status()

    @app.delete("/runs/{run_id}", dependencies=[Guard])
    async def stop(run_id: str) -> dict:
        _run(run_id)
        await manager.stop(run_id)
        return manager.runs[run_id].status()

    @app.post("/stop-all", dependencies=[Guard])
    async def stop_all() -> dict:
        await manager.stop_all()
        return manager.status()

    return app
