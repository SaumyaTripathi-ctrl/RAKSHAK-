"""Generate the SYNTHETIC food cold-storage / FPO pack-house / ripening-chamber dataset.

    python -m rakshak_ml.facilities_gen            # rewrites data/cold_storage_synthetic.csv

Every row is fabricated (``data_source=synthetic``, names carry "(SYNTHETIC)"). Only the *towns* are real places
(approximate centre coordinates) so that routes in the demo look plausible; no facility here exists. To replace
it with real data use an official list (e.g. NHB / state agriculture departments) with the same columns and
``data_source`` set to its provenance.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent / "data" / "cold_storage_synthetic.csv"

# town, state, lat, lon  (approximate town centres)
TOWNS = [
    ("Pune", "Maharashtra", 18.5204, 73.8567), ("Mumbai", "Maharashtra", 19.0760, 72.8777),
    ("Nashik", "Maharashtra", 19.9975, 73.7898), ("Nagpur", "Maharashtra", 21.1458, 79.0882),
    ("Chhatrapati Sambhajinagar", "Maharashtra", 19.8762, 75.3433), ("Kolhapur", "Maharashtra", 16.7050, 74.2433),
    ("Satara", "Maharashtra", 17.6805, 74.0183), ("Sangli", "Maharashtra", 16.8524, 74.5815),
    ("Ratnagiri", "Maharashtra", 16.9902, 73.3120), ("Chiplun", "Maharashtra", 17.5333, 73.5167),
    ("Solapur", "Maharashtra", 17.6599, 75.9064), ("Jalgaon", "Maharashtra", 21.0077, 75.5626),
    ("Ahmednagar", "Maharashtra", 19.0948, 74.7480), ("Dhule", "Maharashtra", 20.9042, 74.7749),
    ("Alibag", "Maharashtra", 18.6414, 72.8722), ("Kudal", "Maharashtra", 16.0108, 73.6890),
    ("Ahmedabad", "Gujarat", 23.0225, 72.5714), ("Anand", "Gujarat", 22.5645, 72.9289),
    ("Vadodara", "Gujarat", 22.3072, 73.1812), ("Surat", "Gujarat", 21.1702, 72.8311),
    ("Rajkot", "Gujarat", 22.3039, 70.8022), ("Mehsana", "Gujarat", 23.5880, 72.3693),
    ("Junagadh", "Gujarat", 21.5222, 70.4579), ("Bhavnagar", "Gujarat", 21.7645, 72.1519),
    ("Bengaluru", "Karnataka", 12.9716, 77.5946), ("Belagavi", "Karnataka", 15.8497, 74.4977),
    ("Hubballi", "Karnataka", 15.3647, 75.1240), ("Mysuru", "Karnataka", 12.2958, 76.6394),
    ("Kolar", "Karnataka", 13.1367, 78.1292), ("Indore", "Madhya Pradesh", 22.7196, 75.8577),
    ("Hyderabad", "Telangana", 17.3850, 78.4867),
]  # fmt: skip

# (kind, label, setpoint range C, capacity tonnes range)
KINDS = {
    "chiller": ("cold_storage", "Chilled store (leafy greens / dairy)", (0.0, 4.0), (20, 200)),
    "multi": ("cold_storage", "Multi-commodity cold store", (2.0, 14.0), (100, 1500)),
    "fruitveg": ("cold_storage", "Fruit & vegetable cold store", (10.0, 14.0), (50, 800)),
    "packhouse": ("fpo_packhouse", "FPO pack-house pre-cooling room", (8.0, 16.0), (5, 60)),
    "ripening": ("ripening_chamber", "Ripening chamber", (15.0, 22.0), (10, 80)),
}
WEIGHTS = {"chiller": 0.15, "multi": 0.30, "fruitveg": 0.25, "packhouse": 0.15, "ripening": 0.15}

COLUMNS = [
    "id", "name", "type", "state", "town", "lat", "lng",
    "storage_min", "storage_max", "capacity_tonnes", "free_tonnes", "active", "data_source",
]  # fmt: skip


def generate(seed: int = 26232) -> list[dict]:
    rng = np.random.default_rng(seed)
    kinds, probs = list(WEIGHTS), np.array(list(WEIGHTS.values()))
    rows = []
    n = 0
    for town, state, lat, lon in TOWNS:
        for _ in range(int(rng.integers(3, 8))):
            n += 1
            key = str(rng.choice(kinds, p=probs / probs.sum()))
            ftype, label, (smin, smax), (clo, chi) = KINDS[key]
            cap = int(rng.integers(clo, chi + 1))
            rows.append(
                {
                    "id": f"SYN-{n:04d}",
                    "name": f"{label} #{n} near {town} (SYNTHETIC)",
                    "type": ftype,
                    "state": state,
                    "town": town,
                    "lat": round(float(lat + rng.normal(0, 0.12)), 5),
                    "lng": round(float(lon + rng.normal(0, 0.12)), 5),
                    "storage_min": smin,
                    "storage_max": smax,
                    "capacity_tonnes": cap,
                    "free_tonnes": round(float(cap * rng.uniform(0.05, 0.6)), 1),
                    "active": bool(rng.random() < 0.92),
                    "data_source": "synthetic",
                }
            )
    return rows


def main() -> None:
    rows = generate()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} SYNTHETIC facilities to {OUT}")


if __name__ == "__main__":
    main()
