"""Turn simulated shipments into model-ready frames (features via the production FeatureEngine)."""

from __future__ import annotations

import pandas as pd

from .bands import load_bands
from .features import FEATURES, FeatureEngine, Reading
from .sim import ShipmentSim, SimConfig

PROFILES: dict[str, dict] = {
    # real: physical time, trips of 12-72 h, one record every 5 minutes
    "real": {"time_scale": 1.0, "duration_h": (12.0, 72.0), "step_min": 5.0},
    # demo: time compressed 24x so a few minutes of live demo cover days of physics. NOT for real use.
    "demo": {"time_scale": 24.0, "duration_h": (1.5, 5.0), "step_min": 1.0},
}

META_COLUMNS = ["shipment_id", "food_type", "step", "t_min"]
LABEL_COLUMNS = ["risk_true", "rsl_true_h"]
DIAGNOSTIC_COLUMNS = ["consumed", "rate_factor", "ripeness", "in_excursion"]


def rows_to_frame(rows: list[dict]) -> pd.DataFrame:
    """Run the FeatureEngine over one shipment's simulated rows."""
    from .bands import get_band

    engine = FeatureEngine(get_band(rows[0]["food_type"]))
    out = []
    for r in rows:
        feats = engine.update(
            Reading(
                t=r["t_min"] * 60.0,
                temperature=r["temperature"],
                humidity=r["humidity"],
                ethylene_index=r["ethylene_index"],
                shock_g=r["shock_g"],
                external_temperature=r["external_temperature"],
                external_humidity=r["external_humidity"],
                rain_probability=r["rain_probability"],
                wind_speed=r["wind_speed"],
                flap_position=r["flap_position"],
                scrubber_on=r["scrubber_on"],
            )
        )
        out.append(
            {
                **{k: r[k] for k in META_COLUMNS},
                **feats,
                **{k: r[k] for k in LABEL_COLUMNS + DIAGNOSTIC_COLUMNS},
            }
        )
    return pd.DataFrame(out)


def generate_dataset(
    n_per_food: int, profile: str = "real", seed: int = 42, stride: int = 1
) -> pd.DataFrame:
    """Simulate ``n_per_food`` shipments of every food type. ``stride`` subsamples rows *after* features."""
    spec = PROFILES[profile]
    frames = []
    foods = sorted(load_bands())
    import numpy as np

    for fi, food in enumerate(foods):
        for i in range(n_per_food):
            s = seed * 1_000_003 + fi * 10_007 + i
            rng = np.random.default_rng(s ^ 0xABCDEF)
            lo, hi = spec["duration_h"]
            cfg = SimConfig(
                food_type=food,
                duration_h=float(rng.uniform(lo, hi)),
                step_min=spec["step_min"],
                time_scale=spec["time_scale"],
                seed=s,
                shipment_id=f"SIM-{profile[0].upper()}{fi}{i:05d}",
            )
            df = rows_to_frame(ShipmentSim(cfg).run())
            frames.append(df.iloc[::stride] if stride > 1 else df)
    data = pd.concat(frames, ignore_index=True)
    assert set(FEATURES) <= set(data.columns)
    return data
