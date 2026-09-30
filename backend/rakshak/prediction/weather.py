"""Open-Meteo (rain probability, wind) with a cache; never blocks or fails the prediction path."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import httpx

log = logging.getLogger("rakshak.weather")


@dataclass(frozen=True)
class Weather:
    rain_probability: float = 0.0  # 0..1
    wind_speed: float = 0.0  # km/h
    source: str = "default"  # "open-meteo" | "default"


class WeatherClient:
    def __init__(
        self,
        *,
        enabled: bool = False,
        base_url: str = "https://api.open-meteo.com",
        transport: httpx.AsyncBaseTransport | None = None,
        ttl_s: float = 1800.0,
        timeout: float = 3.0,
        backoff_s: float = 300.0,
    ) -> None:
        self.enabled = enabled
        self._http = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=timeout)
        self._ttl, self._backoff = ttl_s, backoff_s
        self._cache: dict[tuple, tuple[float, Weather]] = {}
        self._down_until = 0.0
        self._refreshing: set[tuple] = set()
        self._tasks: set[asyncio.Task] = set()

    async def get(self, lat: float | None, lon: float | None) -> Weather:
        if not self.enabled or lat is None or lon is None:
            return Weather()
        key = (round(lat, 1), round(lon, 1))  # ~11 km cells
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit and now - hit[0] < self._ttl:
            return hit[1]
        if now < self._down_until:
            return hit[1] if hit else Weather()
        try:
            r = await self._http.get(
                "/v1/forecast",
                params={
                    "latitude": f"{lat:.3f}",
                    "longitude": f"{lon:.3f}",
                    "current": "wind_speed_10m",
                    "hourly": "precipitation_probability",
                    "forecast_hours": 1,
                },
            )
            r.raise_for_status()
            d = r.json()
            rain = (d.get("hourly", {}).get("precipitation_probability") or [0])[0] or 0
            w = Weather(
                float(rain) / 100.0,
                float(d.get("current", {}).get("wind_speed_10m") or 0.0),
                "open-meteo",
            )
        except Exception as exc:
            log.warning("weather unavailable (%s)", exc)
            self._down_until = now + self._backoff
            return hit[1] if hit else Weather()
        self._cache[key] = (now, w)
        return w

    def peek(self, lat: float | None, lon: float | None) -> Weather:
        """Non-blocking: the cached value (or default) now; a stale/missing entry is refreshed in the
        background so the ingest path never waits on the network."""
        if not self.enabled or lat is None or lon is None:
            return Weather()
        key = (round(lat, 1), round(lon, 1))
        hit = self._cache.get(key)
        fresh = hit is not None and time.monotonic() - hit[0] < self._ttl
        if not fresh and key not in self._refreshing:
            self._refreshing.add(key)
            task = asyncio.create_task(self._refresh(key, lat, lon))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return hit[1] if hit else Weather()

    async def _refresh(self, key: tuple, lat: float, lon: float) -> None:
        try:
            await self.get(lat, lon)
        finally:
            self._refreshing.discard(key)

    async def aclose(self) -> None:
        await self._http.aclose()
