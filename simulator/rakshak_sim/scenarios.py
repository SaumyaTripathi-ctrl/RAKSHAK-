"""Scripted trips. Times are *device minutes* since departure. All of it is SIMULATED.

The default ``profile`` is ``demo``: physics and the matching *demo* model pair are time-compressed 24x, so a
2-3 hour trip shows the spoilage story (risk climbing, flap opening, fan switching on) in a few real minutes.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Step:
    at: float
    action: str
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Scenario:
    name: str
    title: str
    description: str
    food_type: str
    duration_min: float
    steps: tuple[Step, ...] = ()
    profile: str = "demo"
    accel: float = 60.0  # device seconds per real second
    physics: dict = field(default_factory=dict)
    has_pcm: bool = True
    has_scrubber: bool | None = None
    ambient: float | None = None  # None = refrigerated/cold-chain truck: food band mid + 1 C
    origin: tuple[float, float] | None = None  # default: the shipment's own origin/destination
    dest: tuple[float, float] | None = None
    handovers: bool = (
        True  # FARM at start, TRANSPORT after loading, COLD_STORAGE/RETAIL + close at the end
    )


def S(at: float, action: str, **params) -> Step:
    return Step(at, action, params)


SCENARIOS: dict[str, Scenario] = {
    s.name: s
    for s in (
        Scenario(
            "normal_trip",
            "Normal trip",
            "Pre-cooled mango, steady in-band conditions: risk stays SAFE, nothing to do.",
            "mango",
            duration_min=120,
            physics={"tau_h": 30.0, "pcm_cap0": 80.0},
        ),
        Scenario(
            "heat_excursion",
            "Heat excursion",
            "A hot spell warms the load: the hub opens the PCM flap (25/50/100 %) with no network needed; "
            "risk climbs to WARNING.",
            "mango",
            duration_min=150,
            physics={"tau_h": 10.0, "pcm_cap0": 45.0},
            steps=(S(20, "heat", extra_c=13), S(75, "heat", extra_c=0)),
        ),
        Scenario(
            "banana_ripening",
            "Banana ripening",
            "A mixed load raises ethylene; the index climbs, the hub switches the scrubber fan on, and the index "
            "falls once the source is gone.",
            "banana",
            duration_min=180,
            physics={"tau_h": 40.0, "pcm_cap0": 80.0},
            has_scrubber=True,
            steps=(S(10, "ethylene", units_per_h=30), S(70, "ethylene", units_per_h=0)),
        ),
        Scenario(
            "rural_no_network",
            "Rural no-network stretch",
            "4G drops for 60 minutes: the hub keeps sensing and acting, queues encrypted records, then bursts them "
            "to the broker when the network returns.",
            "mango",
            duration_min=150,
            physics={"tau_h": 14.0, "pcm_cap0": 60.0},
            steps=(S(30, "heat", extra_c=8), S(40, "network_cut"), S(100, "network_restore")),
        ),
        Scenario(
            "tamper",
            "Tamper attempts",
            "A lid is opened, a record is edited, a record is deleted, and finally a database row is edited: every "
            "one is detected (events, then Verify shows TAMPERED).",
            "mango",
            duration_min=130,
            physics={"tau_h": 30.0, "pcm_cap0": 80.0},
            steps=(
                S(30, "lid_open"),
                S(45, "tamper_forge"),
                S(60, "tamper_delete"),
                S(95, "anchor"),
                S(100, "tamper_db", kind="edit_value"),
            ),
        ),
        Scenario(
            "critical_reroute",
            "Critical - reroute",
            "Cooling fails on a hot day: risk reaches CRITICAL, the AI commands the hub, finds the nearest "
            "compatible cold store, and the truck follows the detour.",
            "mango",
            duration_min=240,
            has_pcm=False,
            physics={"tau_h": 6.0},
            steps=(S(10, "heat", extra_c=14), S(1, "follow_reroute")),
        ),
        Scenario(
            "demo_full",
            "Full demo",
            "Heat -> flap opens -> ethylene rises -> fan on -> network cut -> logging continues -> reconnect -> backlog "
            "syncs -> CRITICAL -> reroute -> tamper -> Verify shows TAMPERED.",
            "mango",
            duration_min=260,
            physics={"tau_h": 6.0, "pcm_cap0": 26.0},
            has_scrubber=True,
            steps=(
                S(12, "heat", extra_c=12),
                S(28, "ethylene", units_per_h=45),
                S(55, "network_cut"),
                S(85, "network_restore"),
                S(95, "follow_reroute"),
                S(150, "lid_open"),
                S(155, "tamper_forge"),
                S(160, "tamper_delete"),
                S(175, "anchor"),
                S(180, "tamper_db", kind="edit_value"),
            ),
        ),
    )
}


def get_scenario(name: str) -> Scenario:
    try:
        return SCENARIOS[name]
    except KeyError as exc:
        raise KeyError(f"unknown scenario {name!r}; available: {', '.join(SCENARIOS)}") from exc
