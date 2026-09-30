"""Food cold-storage / pack-house / ripening-chamber dataset (SYNTHETIC unless replaced)."""

from __future__ import annotations

import csv
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from rakshak_ml.bands import FoodBand

DEFAULT_CSV = (
    Path(__import__("rakshak_ml").__file__).resolve().parent / "data" / "cold_storage_synthetic.csv"
)


@dataclass(frozen=True)
class Facility:
    id: str
    name: str
    type: str
    state: str
    town: str
    lat: float
    lng: float
    storage_min: float
    storage_max: float
    capacity_tonnes: float
    free_tonnes: float
    active: bool
    data_source: str

    def to_dict(self) -> dict:
        return asdict(self)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line distance. A FALLBACK/pre-filter only - not road distance."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


def load_facilities(path: str | Path | None = None) -> list[Facility]:
    rows = []
    with Path(path or DEFAULT_CSV).open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            rows.append(
                Facility(
                    id=r["id"],
                    name=r["name"],
                    type=r["type"],
                    state=r.get("state", ""),
                    town=r.get("town", ""),
                    lat=float(r["lat"]),
                    lng=float(r["lng"]),
                    storage_min=float(r["storage_min"]),
                    storage_max=float(r["storage_max"]),
                    capacity_tonnes=float(r["capacity_tonnes"]),
                    free_tonnes=float(r.get("free_tonnes") or r["capacity_tonnes"]),
                    active=r["active"].strip().lower() in ("1", "true", "yes"),
                    data_source=r["data_source"],
                )
            )
    return rows


def compatible(f: Facility, band: FoodBand, weight_kg: float = 0.0, slack_c: float = 1.0) -> bool:
    """Active, enough free room, and its setpoint range overlaps the food's band (+- slack)."""
    if not f.active or f.free_tonnes * 1000 < weight_kg:
        return False
    return f.storage_min <= band.max_temp + slack_c and f.storage_max >= band.min_temp - slack_c
