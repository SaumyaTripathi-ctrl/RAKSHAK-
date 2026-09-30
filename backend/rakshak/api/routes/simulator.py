"""Admin proxy to the device simulator's control API (the simulator container is internal-only)."""

from __future__ import annotations

from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status

from ...db.models import Role, User
from ..deps import require_roles

router = APIRouter(prefix="/api/simulator", tags=["simulator (SIMULATED devices)"])
Admin = Annotated[User, Depends(require_roles(Role.ADMIN.value))]


async def _forward(request: Request, method: str, path: str, body: Any = None) -> Any:
    client: httpx.AsyncClient | None = getattr(request.app.state, "simulator_client", None)
    if client is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "no simulator configured (RAKSHAK_SIMULATOR_URL)"
        )
    try:
        r = await client.request(method, path, json=body)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"simulator not reachable: {exc}"
        ) from exc
    if r.status_code >= 400:
        detail = (
            r.json().get("detail", r.text)
            if r.headers.get("content-type", "").startswith("application/json")
            else r.text
        )
        raise HTTPException(r.status_code, detail)
    return r.json()


@router.get("/scenarios")
async def scenarios(request: Request, _: Admin) -> Any:
    return await _forward(request, "GET", "/scenarios")


@router.get("/state")
async def state(request: Request, _: Admin) -> Any:
    return await _forward(request, "GET", "/state")


@router.post("/runs", status_code=status.HTTP_201_CREATED)
async def start(body: dict, request: Request, _: Admin) -> Any:
    return await _forward(request, "POST", "/runs", body)


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request, _: Admin) -> Any:
    return await _forward(request, "GET", f"/runs/{run_id}")


@router.post("/runs/{run_id}/inject")
async def inject(run_id: str, body: dict, request: Request, _: Admin) -> Any:
    return await _forward(request, "POST", f"/runs/{run_id}/inject", body)


@router.post("/runs/{run_id}/pause")
async def pause(run_id: str, request: Request, _: Admin) -> Any:
    return await _forward(request, "POST", f"/runs/{run_id}/pause")


@router.post("/runs/{run_id}/resume")
async def resume(run_id: str, request: Request, _: Admin) -> Any:
    return await _forward(request, "POST", f"/runs/{run_id}/resume")


@router.delete("/runs/{run_id}")
async def stop(run_id: str, request: Request, _: Admin) -> Any:
    return await _forward(request, "DELETE", f"/runs/{run_id}")


@router.post("/stop-all")
async def stop_all(request: Request, _: Admin) -> Any:
    return await _forward(request, "POST", "/stop-all")
