"""SAFE / WARNING / CRITICAL alert state machine (ported from the MedRakshak firmware logic).

* Risk < 30 -> SAFE, 30..70 -> WARNING, >= 70 -> CRITICAL.
* Escalation is immediate; recovery needs the lower level to persist for ``recovery_hold_s`` (15 s by default,
  measured in *data time*, so it works when the simulator accelerates the clock).
* CRITICAL **latches** the alarm (buzzer): it stays latched until ``acknowledge()`` even after the level recovers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

WARNING_AT = 30.0
CRITICAL_AT = 70.0


class Level(IntEnum):
    SAFE = 0
    WARNING = 1
    CRITICAL = 2


def level_for_risk(risk: float) -> Level:
    if risk >= CRITICAL_AT:
        return Level.CRITICAL
    if risk >= WARNING_AT:
        return Level.WARNING
    return Level.SAFE


@dataclass(frozen=True)
class Transition:
    previous: Level
    current: Level
    at: float
    newly_latched: bool

    @property
    def escalated(self) -> bool:
        return self.current > self.previous


class AlertStateMachine:
    def __init__(self, recovery_hold_s: float = 15.0) -> None:
        self.recovery_hold_s = recovery_hold_s
        self.level = Level.SAFE
        self.latched = False
        self._lower_since: float | None = None

    def update(self, risk: float, t: float) -> Transition | None:
        """``t`` in seconds (any monotonic data-time). Returns a Transition when the level changed."""
        target = level_for_risk(risk)
        prev = self.level
        if target > self.level:
            self.level = target
            self._lower_since = None
        elif target < self.level:
            if self._lower_since is None:
                self._lower_since = t
            if t - self._lower_since >= self.recovery_hold_s:
                self.level = target
                self._lower_since = None
        else:
            self._lower_since = None
        newly_latched = False
        if (
            self.level is Level.CRITICAL and prev is not Level.CRITICAL
        ):  # latch on *entering* CRITICAL only
            self.latched = newly_latched = True
        if self.level != prev:
            return Transition(prev, self.level, t, newly_latched)
        return None

    def acknowledge(self) -> bool:
        """Silence the latched alarm. Returns True if it was latched."""
        was = self.latched
        self.latched = False
        return was
