"""Backend API client used by scenario runs (create shipments, hand-overs, reroute, demo tamper)."""

from __future__ import annotations

import logging
import os
from typing import Protocol

import httpx

from .routes import route_for

log = logging.getLogger("rakshak.sim.api")

STAGE_USER = {  # who signs which hand-over (dev accounts from the seed data)
    "FARM": "fpo",
    "FPO": "fpo",
    "PACKHOUSE": "fpo",
    "COLD_STORAGE": "fpo",
    "TRANSPORT": "driver",
    "RETAIL": "exporter",
}


class ApiClient(Protocol):
    async def list_devices(self, kind: str | None = None) -> list[dict]: ...
    async def device(self, device_id: str) -> dict | None: ...
    async def shipment(self, shipment_id: str) -> dict | None: ...
    async def ensure_shipment(self, **kw) -> dict: ...
    async def handover(self, shipment_id: str, stage: str, location: str = "") -> None: ...
    async def anchor(self, shipment_id: str) -> None: ...
    async def close(self, shipment_id: str) -> None: ...
    async def live(self, shipment_id: str) -> dict | None: ...
    async def reroute(self, shipment_id: str) -> dict | None: ...
    async def accept_reroute(self, shipment_id: str, facility_id: str) -> dict | None: ...
    async def demo_tamper(self, shipment_id: str, kind: str) -> dict | None: ...
    async def aclose(self) -> None: ...


class HttpApi:
    def __init__(self, base_url: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), transport=transport, timeout=30
        )
        self._tokens: dict[str, str] = {}

    @staticmethod
    def _password(user: str) -> str:
        return os.environ.get(f"SIM_PASSWORD_{user.upper()}", f"{user}123")  # dev seed passwords

    async def _token(self, user: str) -> str:
        if user not in self._tokens:
            r = await self._http.post(
                "/api/auth/login", json={"username": user, "password": self._password(user)}
            )
            r.raise_for_status()
            self._tokens[user] = r.json()["access_token"]
        return self._tokens[user]

    async def _call(self, method: str, path: str, user: str = "admin", **kw) -> httpx.Response:
        for attempt in (1, 2):
            token = await self._token(user)
            r = await self._http.request(
                method, path, headers={"Authorization": f"Bearer {token}"}, **kw
            )
            if r.status_code == 401 and attempt == 1:
                self._tokens.pop(user, None)  # expired: log in again once
                continue
            return r
        return r

    async def list_devices(self, kind: str | None = None) -> list[dict]:
        r = await self._call("GET", "/api/devices", params={"kind": kind} if kind else None)
        r.raise_for_status()
        return r.json()

    async def device(self, device_id: str) -> dict | None:
        r = await self._call("GET", f"/api/devices/{device_id}")
        return r.json() if r.status_code == 200 else None

    async def shipment(self, shipment_id: str) -> dict | None:
        r = await self._call("GET", f"/api/shipments/{shipment_id}")
        return r.json() if r.status_code == 200 else None

    async def ensure_shipment(
        self,
        *,
        hub_id,
        tag_ids,
        food_type,
        profile,
        origin=None,
        dest=None,
        weight_kg=1000.0,
        origin_name=None,
        dest_name=None,
        reuse=True,
    ) -> dict:
        """Reuse the hub's current open shipment (so the seeded ones come alive) or create a new one."""
        hub = await self.device(hub_id)
        if reuse and hub and hub.get("shipment_id"):
            sh = await self.shipment(hub["shipment_id"])
            if sh and sh["status"] != "DELIVERED":
                r = await self._call(
                    "PUT",
                    f"/api/shipments/{sh['id']}/model-profile",
                    json={"model_profile": profile},
                )
                r.raise_for_status()
                return {**sh, "model_profile": profile}
        if (
            origin is None and dest is None
        ):  # a created shipment always gets a real route (Ratnagiri -> Pune)
            default = route_for(0)
            origin, dest = default["origin"], default["dest"]
            origin_name = origin_name or default["origin_name"]
            dest_name = dest_name or default["dest_name"]
        body = {
            "food_type": food_type,
            "variety": "simulated",
            "weight_kg": weight_kg,
            "origin_name": origin_name or "Simulated origin",
            "origin_lat": origin[0] if origin else None,
            "origin_lon": origin[1] if origin else None,
            "dest_name": dest_name or "Simulated destination",
            "dest_lat": dest[0] if dest else None,
            "dest_lon": dest[1] if dest else None,
            "hub_id": hub_id,
            "tag_ids": tag_ids,
            "model_profile": profile,
        }
        r = await self._call("POST", "/api/shipments", "fpo", json=body)
        r.raise_for_status()
        return r.json()

    async def handover(self, shipment_id: str, stage: str, location: str = "") -> None:
        r = await self._call(
            "POST",
            f"/api/shipments/{shipment_id}/handover",
            STAGE_USER.get(stage, "admin"),
            json={"stage": stage, "location": location or f"{stage.title()} (simulated)"},
        )
        if r.status_code >= 400:
            log.warning("hand-over %s failed: %s %s", stage, r.status_code, r.text[:200])

    async def anchor(self, shipment_id: str) -> None:
        await self._call("POST", f"/api/shipments/{shipment_id}/anchor", "fpo")

    async def close(self, shipment_id: str) -> None:
        await self._call("POST", f"/api/shipments/{shipment_id}/close", "fpo")

    async def live(self, shipment_id: str) -> dict | None:
        r = await self._call("GET", f"/api/shipments/{shipment_id}/live")
        return r.json() if r.status_code == 200 else None

    async def route(self, a: tuple[float, float], b: tuple[float, float]) -> dict | None:
        r = await self._call(
            "GET",
            "/api/route",
            params={"from_lat": a[0], "from_lon": a[1], "to_lat": b[0], "to_lon": b[1]},
        )
        return r.json() if r.status_code == 200 else None

    async def reroute(self, shipment_id: str) -> dict | None:
        r = await self._call("GET", f"/api/shipments/{shipment_id}/reroute")
        return r.json() if r.status_code == 200 else None

    async def accept_reroute(self, shipment_id: str, facility_id: str) -> dict | None:
        r = await self._call(
            "POST",
            f"/api/shipments/{shipment_id}/reroute/accept",
            "driver",
            json={"facility_id": facility_id},
        )
        return r.json() if r.status_code == 200 else None

    async def demo_tamper(self, shipment_id: str, kind: str) -> dict | None:
        r = await self._call(
            "POST", "/api/demo/tamper", json={"shipment_id": shipment_id, "kind": kind}
        )
        return (
            r.json() if r.status_code == 200 else {"error": r.text[:200], "status": r.status_code}
        )

    async def aclose(self) -> None:
        await self._http.aclose()
