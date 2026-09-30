"""Nearest *compatible* cold store for an endangered shipment."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from rakshak_ml.bands import FoodBand

from .facilities import Facility, compatible, haversine_km
from .routing import Router


@dataclass
class RerouteOption:
    facility: Facility
    straight_km: float
    distance_km: float
    duration_min: float
    routing_source: str
    status: str
    reachable_before_spoilage: bool | None
    geometry: list[list[float]] | None
    note: str | None = None

    def to_dict(self, *, with_geometry: bool = True) -> dict:
        d = {
            "facility": self.facility.to_dict(),
            "straight_km": round(self.straight_km, 2),
            "distance_km": self.distance_km,
            "duration_min": self.duration_min,
            "routing_source": self.routing_source,
            "routing_status": self.status,
            "reachable_before_spoilage": self.reachable_before_spoilage,
            "note": self.note,
        }
        if with_geometry:
            d["geometry"] = self.geometry
        return d


@dataclass
class RerouteRecommendation:
    origin: tuple[float, float]
    recommended: RerouteOption | None
    alternatives: list[RerouteOption]
    reason: str

    def to_dict(self) -> dict:
        return {
            "origin": {"lat": self.origin[0], "lon": self.origin[1]},
            "recommended": self.recommended.to_dict() if self.recommended else None,
            "alternatives": [a.to_dict() for a in self.alternatives],
            "reason": self.reason,
        }


async def recommend(
    router: Router,
    facilities: list[Facility],
    band: FoodBand,
    origin: tuple[float, float],
    *,
    weight_kg: float = 0.0,
    rsl_hours: float | None = None,
    candidates: int = 6,
    alternatives: int = 2,
    exclude: frozenset[str] = frozenset(),
) -> RerouteRecommendation:
    ok = [f for f in facilities if f.id not in exclude and compatible(f, band, weight_kg)]
    if not ok:
        return RerouteRecommendation(
            origin, None, [], f"no active compatible facility for {band.food_type}"
        )
    ok.sort(key=lambda f: haversine_km(origin[0], origin[1], f.lat, f.lng))
    near = ok[:candidates]  # pre-filter by straight line, then ask the router only for these
    routes = await asyncio.gather(*(router.route(origin, (f.lat, f.lng)) for f in near))
    options = []
    for f, r in zip(near, routes, strict=True):
        eta_h = r.duration_min / 60.0
        options.append(
            RerouteOption(
                f,
                haversine_km(origin[0], origin[1], f.lat, f.lng),
                r.distance_km,
                r.duration_min,
                r.source,
                r.status,
                None if rsl_hours is None else eta_h < rsl_hours,
                r.geometry,
                r.note,
            )
        )
    # Prefer options that get there before spoilage; then fastest road time.
    options.sort(key=lambda o: (o.reachable_before_spoilage is False, o.duration_min))
    best, rest = options[0], options[1 : 1 + alternatives]
    reason = (
        f"nearest of {len(ok)} compatible facilities by road time "
        f"({band.food_type} band {band.min_temp:g}-{band.max_temp:g} C)"
    )
    if best.reachable_before_spoilage is False:
        reason += "; WARNING: estimated travel time exceeds the remaining safe life"
    return RerouteRecommendation(origin, best, rest, reason)
