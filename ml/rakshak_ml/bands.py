"""Food storage bands (``data/food_bands.json``)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

ALIASES = {
    "mangoes": "mango",
    "bananas": "banana",
    "tomatoes": "tomato",
    "leafy": "leafy_vegetables",
    "leafy_veg": "leafy_vegetables",
    "spinach": "leafy_vegetables",
    "lettuce": "leafy_vegetables",
    "dairy": "milk",
}


@dataclass(frozen=True)
class FoodBand:
    food_type: str
    min_temp: float
    max_temp: float
    min_rh: float
    max_rh: float
    ethylene_sensitive: bool
    ethylene_producer: bool
    nominal_shelf_life_h: float  # simulator assumption, see food_bands.json
    source: str
    verification_status: str

    @property
    def mid_temp(self) -> float:
        return (self.min_temp + self.max_temp) / 2

    @property
    def chilling_sensitive(self) -> bool:
        """Tropical/sub-tropical produce is damaged below its band; leafy greens and milk are not."""
        return self.food_type in ("mango", "banana", "tomato")


@lru_cache
def load_bands(path: str | None = None) -> dict[str, FoodBand]:
    raw = json.loads(Path(path or DATA_DIR / "food_bands.json").read_text(encoding="utf-8"))
    out: dict[str, FoodBand] = {}
    for name, v in raw["foods"].items():
        out[name] = FoodBand(
            food_type=name,
            min_temp=float(v["min_temp"]),
            max_temp=float(v["max_temp"]),
            min_rh=float(v["min_rh"]),
            max_rh=float(v["max_rh"]),
            ethylene_sensitive=bool(v["ethylene_sensitive"]),
            ethylene_producer=bool(v["ethylene_producer"]),
            nominal_shelf_life_h=float(v["nominal_shelf_life_h"]),
            source=v["source"],
            verification_status=v["verification_status"],
        )
    return out


def normalise_food_type(food_type: str) -> str:
    key = food_type.strip().lower().replace(" ", "_").replace("-", "_")
    return ALIASES.get(key, key)


def get_band(food_type: str) -> FoodBand:
    bands = load_bands()
    key = normalise_food_type(food_type)
    if key not in bands:
        raise KeyError(f"unknown food type {food_type!r}; known: {', '.join(sorted(bands))}")
    return bands[key]
