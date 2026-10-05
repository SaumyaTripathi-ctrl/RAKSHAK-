"""Demo routes between real Maharashtra towns (the shipments driving them are SIMULATED)."""

from __future__ import annotations

# name, lat, lon
TOWNS = {
    "Ratnagiri": (16.9902, 73.3120),
    "Pune": (18.5204, 73.8567),
    "Nashik": (19.9975, 73.7898),
    "Mumbai (Vashi APMC)": (19.0760, 72.9980),
    "Kolhapur": (16.7050, 74.2433),
    "Satara": (17.6805, 74.0183),
    "Sangli": (16.8524, 74.5815),
    "Nagpur": (21.1458, 79.0882),
    "Amravati": (20.9374, 77.7796),
    "Chiplun": (17.5330, 73.5160),
}

ROUTES = [
    ("Ratnagiri", "Pune"),
    ("Nashik", "Mumbai (Vashi APMC)"),
    ("Kolhapur", "Pune"),
    ("Satara", "Mumbai (Vashi APMC)"),
    ("Nagpur", "Amravati"),
    ("Sangli", "Pune"),
    ("Chiplun", "Mumbai (Vashi APMC)"),
]


def route_for(i: int) -> dict:
    o, d = ROUTES[i % len(ROUTES)]
    return {
        "origin": TOWNS[o],
        "dest": TOWNS[d],
        "origin_name": f"{o} (demo)",
        "dest_name": f"{d} (demo)",
    }
