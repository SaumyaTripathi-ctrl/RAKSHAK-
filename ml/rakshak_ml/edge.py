"""Edge control rules (reference implementation of what the hub firmware does with NO network).

    dT = crate_temp - upper_limit(food)
    dT <= 0       -> flap 0 %      (inside band: save PCM)
    dT < 1.5 C    -> flap 25 %
    dT < 3 C      -> flap 50 %
    else          -> flap 100 % + WARNING
    ethylene index rising faster than a threshold -> fan ON (through the KMnO4 scrubber)
    ethylene index stable for 30 min              -> fan OFF (saves power + cartridge)

Thresholds are illustrative starting values (see the product explainer); they are constructor arguments
here and constants in ``firmware/hub_esp32s3/src/config.h``. The simulator uses this module as the hub.
"""

from __future__ import annotations

from dataclasses import dataclass, field

FLAP_STEPS = (0, 25, 50, 100)
DEFAULT_FLAP_THRESHOLDS = (0.0, 1.5, 3.0)


def flap_for_deviation(
    temp_c: float,
    upper_limit_c: float,
    thresholds: tuple[float, float, float] = DEFAULT_FLAP_THRESHOLDS,
) -> int:
    d = temp_c - upper_limit_c
    t0, t1, t2 = thresholds
    if d <= t0:
        return 0
    if d < t1:
        return 25
    if d < t2:
        return 50
    return 100


@dataclass
class FanController:
    """Fan ON when the ethylene index rises faster than ``rise_per_min``; OFF after ``stable_min`` minutes of
    not rising. The slope is a least-squares fit over a ``window_min`` window (not sample to sample) so noise on the
    colour strip does not toggle the fan."""

    rise_per_min: float = 0.12
    stable_eps_per_min: float = 0.06
    stable_min: float = 30.0
    window_min: float = 30.0
    min_points: int = 5  # no decision on less than ~20 min of data
    confirm: int = 2  # consecutive "rising" evaluations needed to switch on

    fan_on: bool = False
    _above: int = 0
    _hist: list = field(default_factory=list)
    _stable_since_min: float | None = None

    def _slope(self, t_min: float) -> float | None:
        self._hist = [(t, v) for t, v in self._hist if t_min - t <= self.window_min + 1e-9]
        if len(self._hist) < self.min_points:
            return None
        # least-squares slope: ~3x less noisy than an end-point difference with the same samples
        n = len(self._hist)
        mt = sum(t for t, _ in self._hist) / n
        mv = sum(v for _, v in self._hist) / n
        den = sum((t - mt) ** 2 for t, _ in self._hist)
        return None if den == 0 else sum((t - mt) * (v - mv) for t, v in self._hist) / den

    def update(self, t_min: float, ethylene_idx: float) -> bool:
        if self._hist and t_min <= self._hist[-1][0]:
            return self.fan_on
        self._hist.append((t_min, ethylene_idx))
        rate = self._slope(t_min)
        if rate is None:
            return self.fan_on
        self._above = self._above + 1 if rate > self.rise_per_min else 0
        if self._above >= self.confirm:
            self.fan_on = True
            self._stable_since_min = None
        elif self.fan_on and self._above == 0:
            if rate <= self.stable_eps_per_min:
                if self._stable_since_min is None:
                    self._stable_since_min = t_min
                if t_min - self._stable_since_min >= self.stable_min:
                    self.fan_on = False
                    self._stable_since_min = None
            else:
                self._stable_since_min = None
        return self.fan_on
