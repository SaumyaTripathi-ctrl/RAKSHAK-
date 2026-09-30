"""Road routing via OSRM with caching, a circuit breaker and a labelled Haversine fallback."""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass

import httpx

from .facilities import haversine_km

log = logging.getLogger("rakshak.routing")

FALLBACK_SPEED_KMH = 30.0
MAX_GEOMETRY_POINTS = 200


@dataclass(frozen=True)
class Route:
    distance_km: float
    duration_min: float
    source: str  # "osrm" | "haversine"
    status: str  # "road_route" | "estimated"
    geometry: list[list[float]] | None = None  # [[lat, lon], ...]
    note: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _downsample(points: list[list[float]], limit: int) -> list[list[float]]:
    if len(points) <= limit:
        return points
    step = (len(points) - 1) / (limit - 1)
    return [points[round(i * step)] for i in range(limit)]


class Router:
    def __init__(
        self,
        base_url: str = "https://router.project-osrm.org",
        *,
        enabled: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 4.0,
        ttl_s: float = 3600.0,
        cache_size: int = 2048,
        backoff_s: float = 120.0,
    ) -> None:
        self.enabled = enabled
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), transport=transport, timeout=timeout
        )
        self._ttl, self._cache_size, self._backoff = ttl_s, cache_size, backoff_s
        self._cache: OrderedDict[tuple, tuple[float, Route]] = OrderedDict()
        self._down_until = 0.0
        self.osrm_calls = 0

    @staticmethod
    def _key(a: tuple[float, float], b: tuple[float, float]) -> tuple:
        return (round(a[0], 3), round(a[1], 3), round(b[0], 3), round(b[1], 3))

    def _fallback(self, a, b, note: str) -> Route:
        d = haversine_km(a[0], a[1], b[0], b[1])
        return Route(
            round(d, 2),
            round(d / FALLBACK_SPEED_KMH * 60, 1),
            "haversine",
            "estimated",
            [[a[0], a[1]], [b[0], b[1]]],
            note,
        )

    async def route(self, a: tuple[float, float], b: tuple[float, float]) -> Route:
        key = self._key(a, b)
        hit = self._cache.get(key)
        now = time.monotonic()
        if hit and now - hit[0] < self._ttl:
            self._cache.move_to_end(key)
            return hit[1]
        if not self.enabled:
            return self._fallback(
                a, b, "road routing disabled; distance and ETA are straight-line estimates"
            )
        if now < self._down_until:
            return self._fallback(
                a, b, "road routing temporarily unavailable; estimated from straight-line distance"
            )
        try:
            self.osrm_calls += 1
            r = await self._http.get(
                f"/route/v1/driving/{a[1]:.6f},{a[0]:.6f};{b[1]:.6f},{b[0]:.6f}",
                params={"overview": "simplified", "geometries": "geojson"},
            )
            r.raise_for_status()
            data = r.json()
            if data.get("code") != "Ok" or not data.get("routes"):
                raise RuntimeError(f"OSRM code {data.get('code')}")
            best = data["routes"][0]
            geom = [[lat, lon] for lon, lat in best["geometry"]["coordinates"]]
            route = Route(
                round(best["distance"] / 1000, 2),
                round(best["duration"] / 60, 1),
                "osrm",
                "road_route",
                _downsample(geom, MAX_GEOMETRY_POINTS),
            )
        except (
            Exception
        ) as exc:  # network, HTTP, JSON, shape: all mean "fall back", never "fail the alert"
            log.warning(
                "OSRM unavailable (%s); using Haversine fallback for %.0fs", exc, self._backoff
            )
            self._down_until = now + self._backoff
            return self._fallback(
                a, b, "road routing unavailable; distance and ETA are straight-line estimates"
            )
        self._cache[key] = (now, route)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return route

    async def aclose(self) -> None:
        await self._http.aclose()
