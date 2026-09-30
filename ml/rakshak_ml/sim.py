"""Produce/dairy shipment simulator. **Everything it produces is SIMULATED.**

Physical model (all parameters are assumptions, documented in ``ml/MODEL_CARD.md``):

* ambient temperature: diurnal sinusoid + AR(1) noise; random *heat excursions* (door open, sun, failed cover);
* crate temperature: first-order lag to ambient, respiration heat from ripening, optional PCM cooling that the
  hub's edge rule (``edge.flap_for_deviation``) controls through the flap and that depletes;
* ripening (climacteric fruit): autocatalytic with temperature (Q10-like) and ethylene;
* ethylene concentration: produced by ripening fruit (+ optional mixed-load source), lost by ventilation and, when
  the hub's ``FanController`` switches the scrubber on, removed quickly until the cartridge is exhausted;
* brief sensor-only temperature spikes (door opened next to the sensor) that do not warm the load;
* a hidden per-batch shelf-life multiplier the sensors cannot see (irreducible label noise);
* tag strip index: lagged, noisy reading of that concentration (NOTE: real indicator strips are largely
  irreversible; the simulated index tracks concentration with a lag so the control loop has a signal that can fall);
* shocks: Poisson events with log-normal magnitude;
* ground truth: a hidden consumed-shelf-life fraction driven by temperature (Q10), chilling injury, humidity,
  ethylene, over-ripeness and shock damage -> ``risk_true`` (0-100) and ``rsl_true_h`` (remaining safe life if
  conditions stay as they are now).

``time_scale`` > 1 compresses time (used by the *demo* model pair): each simulated step advances
``time_scale`` times more physical time, so a few hours of demo data cover days of physics.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .bands import FoodBand, get_band
from .edge import FanController, flap_for_deviation

RSL_CAP_H = 240.0

Q10 = {"mango": 2.3, "banana": 2.5, "tomato": 2.2, "leafy_vegetables": 2.8, "milk": 3.0}
RIPEN_TIME_H = {
    "mango": 120.0,
    "banana": 80.0,
    "tomato": 140.0,
}  # base time constant at 20 C (assumption)


@dataclass
class SimConfig:
    food_type: str
    duration_h: float  # data hours (what the device clock sees)
    step_min: float = 5.0
    time_scale: float = 1.0
    seed: int = 0
    shipment_id: str = "SIM-000000"
    # scenario forcing (None = random)
    heat_excursions: int | None = None
    has_pcm: bool | None = None
    has_scrubber: bool | None = None
    mixed_load_ethylene: float | None = None  # units/h exogenous source
    ambient_override: float | None = (
        None  # hold ambient constant (e.g. a cold room); None = weather model
    )
    reading_spikes: list[tuple[float, float, float]] | None = (
        None  # (start_min, length_min, +degC) sensor-only
    )


def _exp_relax(x: float, target: float, k: float, dt: float) -> float:
    """Exact solution of x' = k (target - x); stable for any dt."""
    return target + (x - target) * math.exp(-k * dt)


class ShipmentSim:
    def __init__(self, cfg: SimConfig) -> None:
        self.cfg = cfg
        self.band: FoodBand = get_band(cfg.food_type)
        self.rng = np.random.default_rng(cfg.seed)
        r = self.rng
        b = self.band
        self.ts = cfg.time_scale

        self.base_ambient = float(r.uniform(21, 34))
        self.diurnal_amp = float(r.uniform(4, 8))
        self.phase_h = float(r.uniform(0, 24))
        self.tau_h = float(r.uniform(30, 70) if b.food_type == "milk" else r.uniform(14, 40))
        self.precooled = bool(r.random() < 0.8)
        self.has_pcm = bool(r.random() < 0.6) if cfg.has_pcm is None else cfg.has_pcm
        self.pcm_cap0 = float(r.uniform(30, 120))
        self.has_scrubber = bool(r.random() < 0.6) if cfg.has_scrubber is None else cfg.has_scrubber
        self.scrub_cap0 = float(r.uniform(150, 400))
        self.road_rough = float(r.uniform(1.0, 8.0))  # shocks per physical hour
        n_exc = int(r.poisson(0.8)) if cfg.heat_excursions is None else cfg.heat_excursions
        dur_phys = cfg.duration_h * self.ts
        self.excursions = []
        for _ in range(n_exc):
            start = float(r.uniform(0.05, 0.85) * dur_phys)
            length = float(r.uniform(0.5, 4.0))
            self.excursions.append((start, start + length, float(r.uniform(3, 9))))
        # Hidden, unobservable batch-to-batch variability in shelf life (harvest maturity, handling before
        # the trip). Makes the target genuinely noisy instead of a deterministic function of the sensors.
        self.life_mult = float(r.lognormal(0.0, 0.2))
        if cfg.reading_spikes is not None:
            self.spikes = list(cfg.reading_spikes)
        else:
            dur_min = cfg.duration_h * 60
            self.spikes = [
                (
                    float(r.uniform(0.05, 0.9) * dur_min),
                    float(r.uniform(10, 40)),
                    float(r.uniform(3, 8)),
                )
                for _ in range(int(r.poisson(1.0)))
            ]
        if cfg.mixed_load_ethylene is not None:
            self.ext_eth = cfg.mixed_load_ethylene
        else:
            self.ext_eth = float(r.uniform(3, 15)) if r.random() < 0.2 else 0.0

    # ---------------------------------------------------------------- helpers
    def _excursion(self, t_phys: float) -> tuple[bool, float]:
        for a, z, extra in self.excursions:
            if a <= t_phys < z:
                return True, extra
        return False, 0.0

    def rate_factor(self, temp: float, rh: float, c: float, ripeness: float) -> float:
        b = self.band
        f_t = Q10[b.food_type] ** ((temp - b.mid_temp) / 10.0)
        f_chill = 1.0
        if b.chilling_sensitive and temp < b.min_temp:
            f_chill = 1.0 + 0.35 * (b.min_temp - temp)
        f_rh = 1.0 + 0.03 * max(0.0, b.min_rh - rh) if b.food_type != "milk" else 1.0
        f_eth = 1.0 + (2.0 * (c / 100.0) ** 1.2 if b.ethylene_sensitive else 0.0)
        f_ripe = 1.0 + (1.0 * ripeness**3 if b.ethylene_producer else 0.0)
        return f_t * f_chill * f_rh * f_eth * f_ripe

    # ---------------------------------------------------------------- stepping
    def begin(self) -> None:
        """Initialise the dynamic state (call once before ``step``; ``run`` does it for you)."""
        r, b = self.rng, self.band
        self.i = 0
        self.temp = b.mid_temp + (r.normal(0, 0.5) if self.precooled else r.uniform(1, 4))
        self.rh_ar = 0.0
        self.ripeness = float(r.uniform(0.0, 0.15)) if b.ethylene_producer else 0.0
        self.c = 0.0  # ethylene concentration (0-100 scale)
        self.strip = 0.0
        self.pcm_cap, self.scrub_cap = self.pcm_cap0, self.scrub_cap0
        self.consumed = 0.0
        self.amb_ar = 0.0
        self.rain = float(r.uniform(0, 0.2))
        self.t_pcm = b.min_temp - 3.0 if b.food_type != "milk" else b.min_temp - 1.5
        # Live controls (used by the interactive device simulator; all neutral by default)
        self.manual_heat_c = 0.0  # extra ambient degC (heat wave / failed cover)
        self.manual_eth_units = 0.0  # extra ethylene source (mixed load), units per physical hour
        self.manual_shock_g = 0.0  # one-shot shock, cleared by the next step
        self.manual_spike_c = 0.0  # sensor-only reading offset (door open next to the sensor)

    def step(self, flap: int, fan_on: bool) -> dict:
        """Advance one step. ``flap`` (0/25/50/100) and ``fan_on`` are the actuator states in force during it."""
        cfg, b, r = self.cfg, self.band, self.rng
        i = self.i
        dt_h = cfg.step_min / 60.0 * self.ts  # physical hours per step
        life_h = b.nominal_shelf_life_h * self.life_mult
        t_data_min = i * cfg.step_min
        t_phys = i * dt_h
        # --- environment
        self.amb_ar = 0.9 * self.amb_ar + r.normal(0, 0.8)
        ambient = (
            self.base_ambient
            + self.diurnal_amp * math.sin(2 * math.pi * (t_phys + self.phase_h) / 24.0)
            + self.amb_ar
        )
        if cfg.ambient_override is not None:
            ambient = cfg.ambient_override + 0.3 * self.amb_ar
        in_exc, extra = self._excursion(t_phys)
        in_exc = in_exc or self.manual_heat_c > 0
        amb_eff = ambient + (extra if in_exc else 0.0) + self.manual_heat_c
        tau = self.tau_h / (3.0 if in_exc else 1.0)
        rh_amb = float(np.clip(75 - 1.5 * (ambient - 25) + r.normal(0, 4), 25, 95))

        # --- crate temperature (the hub acts on the *previous* reading, like the firmware loop)
        pcm_ok = self.has_pcm and self.pcm_cap > 0
        flap_frac = flap / 100.0
        resp = 0.4 * self.ripeness if b.ethylene_producer else 0.0
        d_temp = (
            (amb_eff - self.temp) / tau
            - (flap_frac * (self.temp - self.t_pcm) / 4.0 if pcm_ok else 0.0)
            + resp
        )
        self.temp = max(self.temp + d_temp * dt_h, self.t_pcm - 1.0)
        if pcm_ok:
            self.pcm_cap = max(
                0.0, self.pcm_cap - flap_frac * max(self.temp - self.t_pcm, 0.0) * dt_h
            )

        # --- humidity inside the crate
        self.rh_ar = 0.85 * self.rh_ar + r.normal(0, 1.5)
        mid_rh = (b.min_rh + b.max_rh) / 2 if b.food_type != "milk" else 70.0
        rh = float(
            np.clip(
                mid_rh - 1.2 * (self.temp - b.mid_temp) + 0.15 * (rh_amb - 70) + self.rh_ar,
                20,
                100,
            )
        )

        # --- ripening + ethylene
        prod = 0.3 + self.ext_eth + self.manual_eth_units
        if b.ethylene_producer:
            lam = (1.0 / RIPEN_TIME_H[b.food_type]) * 2 ** ((self.temp - 20.0) / 10.0)
            lam *= 1.0 + (0.6 * self.c / 100.0 if b.ethylene_sensitive else 0.0)
            self.ripeness = 1.0 - (1.0 - self.ripeness) * math.exp(-lam * dt_h)
            prod += 50.0 * self.ripeness**1.5
        scrub_k = 2.5 if (fan_on and self.has_scrubber and self.scrub_cap > 0) else 0.0
        k = 0.5 + scrub_k
        self.c = float(np.clip(_exp_relax(self.c, prod / k, k, dt_h), 0, 100))
        if scrub_k:
            self.scrub_cap = max(0.0, self.scrub_cap - self.c * dt_h)
        self.strip = _exp_relax(self.strip, self.c, 1.0 / 0.4, dt_h)
        eth_reading = float(np.clip(round(self.strip + r.normal(0, 1.0), 1), 0, 100))

        # --- shocks
        n_shock = int(r.poisson(self.road_rough * dt_h))
        shock = 0.0
        damage = 0.0
        if n_shock:
            mags = r.lognormal(math.log(0.12), 0.7, size=n_shock)
            shock = float(round(mags.max(), 2))
            damage = float(sum(0.004 * (m - 1.0) ** 2 for m in mags if m > 1.0))
        if self.manual_shock_g > 0:
            shock = max(shock, round(self.manual_shock_g, 2))
            if self.manual_shock_g > 1.0:
                damage += 0.004 * (self.manual_shock_g - 1.0) ** 2
            self.manual_shock_g = 0.0

        # --- ground truth
        rf = self.rate_factor(self.temp, rh, self.c, self.ripeness)
        self.consumed += rf * dt_h / life_h + damage
        risk_true = 100.0 * float(
            np.clip(self.consumed + 0.15 * np.clip((rf - 1.0) / 3.0, 0, 1), 0, 1)
        )
        rsl_phys = float(np.clip((1.0 - self.consumed) * life_h / max(rf, 0.05), 0.0, RSL_CAP_H))

        # --- sensor readings the hub/tags would report
        spike = sum(m for a, ln, m in self.spikes if a <= t_data_min < a + ln) + self.manual_spike_c
        temp_reading = round(float(self.temp + spike + r.normal(0, 0.15)), 2)
        self.rain = float(np.clip(self.rain + r.normal(0, 0.06), 0, 1))
        row = {
            "shipment_id": cfg.shipment_id,
            "food_type": b.food_type,
            "step": i,
            "t_min": t_data_min,
            "temperature": temp_reading,
            "humidity": round(rh, 2),
            "ethylene_index": eth_reading,
            "shock_g": shock,
            "external_temperature": round(float(ambient + r.normal(0, 0.5)), 2),
            "external_humidity": round(rh_amb, 1),
            "rain_probability": round(self.rain, 3),
            "wind_speed": round(float(r.lognormal(math.log(8), 0.5)), 1),
            "flap_position": flap,
            "scrubber_on": int(fan_on and self.has_scrubber),
            # labels / hidden state (never features)
            "consumed": self.consumed,
            "rate_factor": rf,
            "ripeness": self.ripeness,
            "risk_true": risk_true,
            "rsl_true_h": rsl_phys / self.ts,
            "in_excursion": int(in_exc),
            "pcm_remaining": self.pcm_cap,
            "scrubber_remaining": self.scrub_cap,
        }
        self.i += 1
        return row

    # ---------------------------------------------------------------- run
    def run(self) -> list[dict]:
        """Batch mode: the hub's edge rules (flap by temperature, fan by ethylene trend) close the loop."""
        cfg, b = self.cfg, self.band
        n_steps = int(cfg.duration_h * 60 / cfg.step_min)
        self.begin()
        fan = FanController()
        flap, fan_on = 0, False
        rows: list[dict] = []
        for _ in range(n_steps):
            row = self.step(flap, fan_on)
            rows.append(row)
            flap = flap_for_deviation(row["temperature"], b.max_temp)
            fan_on = fan.update(row["t_min"], row["ethylene_index"]) if self.has_scrubber else False
        return rows


def simulate(food_type: str, duration_h: float, seed: int, **kw) -> list[dict]:
    return ShipmentSim(SimConfig(food_type=food_type, duration_h=duration_h, seed=seed, **kw)).run()
