"""Streaming feature engineering (adapted from the MedRakshak pipeline).

One ``FeatureEngine`` per shipment keeps the running state (cumulative exposures, excursions, extremes)
and turns each crate reading into the feature vector the models consume. The *same* code runs in training
(over simulated shipments) and in the backend (over live records), so there is no train/serve skew.

Deliberately NOT a feature: ``cooling_status``. In the MedRakshak demo model that flag leaked the label;
here the actuator state is represented only by ``flap_position`` and ``scrubber_on``, which the hub derives
from sensor readings (they carry no hidden label information).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .bands import FoodBand

BAND_FEATURES = [
    "min_temp",
    "max_temp",
    "min_humidity",
    "max_humidity",
    "ethylene_sensitive",
    "ethylene_producer",
    "nominal_shelf_life_h",
]
LIVE_FEATURES = ["temperature", "humidity", "ethylene_index", "shock_g"]
INSTANT_FEATURES = [
    "temperature_deviation",
    "humidity_deviation",
    "temperature_rate_of_change",  # degC / min
    "ethylene_rate_of_change",  # index points / min
]
CUMULATIVE_FEATURES = [
    "time_outside_temp_range",  # min
    "time_outside_humidity_range",  # min
    "max_temp_deviation",
    "cumulative_temp_exposure",  # degC * min above/below band
    "cumulative_humidity_exposure",  # %RH * min outside band
    "temperature_excursion_count",
    "time_since_first_excursion",  # min
    "cumulative_ethylene_exposure",  # index * min
    "max_ethylene_index",
    "shock_count",
    "max_shock",
    "elapsed_minutes",
]
EXTERNAL_FEATURES = ["external_temperature", "external_humidity", "rain_probability", "wind_speed"]
ACTUATOR_FEATURES = ["flap_position", "scrubber_on"]

FEATURES: list[str] = (
    BAND_FEATURES
    + LIVE_FEATURES
    + INSTANT_FEATURES
    + CUMULATIVE_FEATURES
    + EXTERNAL_FEATURES
    + ACTUATOR_FEATURES
)

# Columns that must never be features (labels, label-derived quantities, known leaks).
FORBIDDEN_FEATURES = {
    "risk_true",
    "rsl_true_h",
    "consumed",
    "rate_factor",
    "ripeness",
    "cooling_status",
    "quality",
    "spoiled",
}

SHOCK_THRESHOLD_G = 0.1
MAX_STEP_MIN = 60.0  # a longer gap is not integrated as exposure (unknown, not assumed)


@dataclass
class Reading:
    """One aggregated crate reading. ``t`` in seconds (epoch or simulation time)."""

    t: float
    temperature: float
    humidity: float
    ethylene_index: float = 0.0
    shock_g: float = 0.0
    external_temperature: float = 25.0
    external_humidity: float = 60.0
    rain_probability: float = 0.0
    wind_speed: float = 0.0
    flap_position: float = 0.0
    scrubber_on: int = 0


@dataclass
class _State:
    first_t: float | None = None
    prev_t: float | None = None
    prev_temp: float | None = None
    prev_eth: float | None = None
    prev_temp_out: bool = False
    prev_hum_out: bool = False
    first_excursion_t: float | None = None
    max_temp_dev: float = 0.0
    time_temp_out: float = 0.0
    time_hum_out: float = 0.0
    cum_temp: float = 0.0
    cum_hum: float = 0.0
    excursions: int = 0
    cum_eth: float = 0.0
    max_eth: float = 0.0
    shock_count: int = 0
    max_shock: float = 0.0
    history: list = field(default_factory=list, repr=False)


def _deviation(v: float, lo: float, hi: float) -> float:
    """Distance outside [lo, hi] (>= 0)."""
    if v < lo:
        return lo - v
    if v > hi:
        return v - hi
    return 0.0


class FeatureEngine:
    def __init__(self, band: FoodBand) -> None:
        self.band = band
        self.s = _State()

    def update(self, r: Reading) -> dict[str, float]:
        b, s = self.band, self.s
        if s.first_t is None:
            s.first_t = r.t
        dt_min = 0.0 if s.prev_t is None else max(0.0, (r.t - s.prev_t) / 60.0)
        step = min(dt_min, MAX_STEP_MIN)

        temp_dev = _deviation(r.temperature, b.min_temp, b.max_temp)
        hum_dev = _deviation(r.humidity, b.min_rh, b.max_rh)
        temp_out, hum_out = temp_dev > 0, hum_dev > 0

        temp_rate = (
            0.0 if s.prev_temp is None or dt_min <= 0 else (r.temperature - s.prev_temp) / dt_min
        )
        eth_rate = (
            0.0 if s.prev_eth is None or dt_min <= 0 else (r.ethylene_index - s.prev_eth) / dt_min
        )

        if temp_out and not s.prev_temp_out:
            s.excursions += 1
            if s.first_excursion_t is None:
                s.first_excursion_t = r.t
        if temp_out:
            s.time_temp_out += step
            s.cum_temp += temp_dev * step
        if hum_out:
            s.time_hum_out += step
            s.cum_hum += hum_dev * step
        s.max_temp_dev = max(s.max_temp_dev, temp_dev)
        s.cum_eth += max(r.ethylene_index, 0.0) * step
        s.max_eth = max(s.max_eth, r.ethylene_index)
        if r.shock_g >= SHOCK_THRESHOLD_G:
            s.shock_count += 1
        s.max_shock = max(s.max_shock, r.shock_g)

        since_first = (
            0.0 if s.first_excursion_t is None else max(0.0, (r.t - s.first_excursion_t) / 60.0)
        )
        feats = {
            "min_temp": b.min_temp,
            "max_temp": b.max_temp,
            "min_humidity": b.min_rh,
            "max_humidity": b.max_rh,
            "ethylene_sensitive": float(b.ethylene_sensitive),
            "ethylene_producer": float(b.ethylene_producer),
            "nominal_shelf_life_h": b.nominal_shelf_life_h,
            "temperature": r.temperature,
            "humidity": r.humidity,
            "ethylene_index": r.ethylene_index,
            "shock_g": r.shock_g,
            "temperature_deviation": temp_dev,
            "humidity_deviation": hum_dev,
            "temperature_rate_of_change": temp_rate,
            "ethylene_rate_of_change": eth_rate,
            "time_outside_temp_range": s.time_temp_out,
            "time_outside_humidity_range": s.time_hum_out,
            "max_temp_deviation": s.max_temp_dev,
            "cumulative_temp_exposure": s.cum_temp,
            "cumulative_humidity_exposure": s.cum_hum,
            "temperature_excursion_count": float(s.excursions),
            "time_since_first_excursion": since_first,
            "cumulative_ethylene_exposure": s.cum_eth,
            "max_ethylene_index": s.max_eth,
            "shock_count": float(s.shock_count),
            "max_shock": s.max_shock,
            "elapsed_minutes": (r.t - s.first_t) / 60.0,
            "external_temperature": r.external_temperature,
            "external_humidity": r.external_humidity,
            "rain_probability": r.rain_probability,
            "wind_speed": r.wind_speed,
            "flap_position": float(r.flap_position),
            "scrubber_on": float(r.scrubber_on),
        }
        s.prev_t, s.prev_temp, s.prev_eth = r.t, r.temperature, r.ethylene_index
        s.prev_temp_out, s.prev_hum_out = temp_out, hum_out
        return feats


def to_vector(feats: dict[str, float], columns: list[str] | None = None) -> list[float]:
    cols = columns or FEATURES
    return [float(feats[c]) for c in cols]
