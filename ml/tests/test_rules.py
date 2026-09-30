"""Bands, edge rules and the alert state machine."""

from __future__ import annotations

import json

import pytest
from rakshak_ml.alert import AlertStateMachine, Level, level_for_risk
from rakshak_ml.bands import DATA_DIR, get_band, load_bands, normalise_food_type
from rakshak_ml.edge import FanController, flap_for_deviation

# ------------------------------------------------------------------ bands


def test_bands_complete_and_sane():
    bands = load_bands()
    assert set(bands) == {"mango", "banana", "tomato", "leafy_vegetables", "milk"}
    for b in bands.values():
        assert b.min_temp < b.max_temp and 0 <= b.min_rh <= b.max_rh <= 100
        assert (
            b.source and b.verification_status == "TODO-verify"
        )  # never claim unchecked values are verified
        assert b.nominal_shelf_life_h > 0
    assert bands["banana"].ethylene_producer and bands["banana"].ethylene_sensitive
    assert (
        bands["leafy_vegetables"].ethylene_sensitive
        and not bands["leafy_vegetables"].ethylene_producer
    )
    assert not bands["milk"].ethylene_sensitive


def test_bands_json_documents_its_own_status():
    meta = json.loads((DATA_DIR / "food_bands.json").read_text(encoding="utf-8"))["_meta"]
    assert (
        "TODO-verify" in meta["status"]
        and "SIMULATOR ASSUMPTION" in meta["nominal_shelf_life_h_note"]
    )


def test_aliases_and_unknown():
    assert get_band("Mangoes").food_type == "mango"
    assert get_band("leafy veg").food_type == "leafy_vegetables"
    assert normalise_food_type(" Leafy-Vegetables ") == "leafy_vegetables"
    with pytest.raises(KeyError, match="known:"):
        get_band("durian")


# ------------------------------------------------------------------ edge rules


@pytest.mark.parametrize(
    "temp,expected",
    [
        (12.0, 0),
        (13.0, 0),
        (13.01, 25),
        (14.49, 25),
        (14.5, 50),
        (15.99, 50),
        (16.0, 100),
        (30, 100),
    ],
)
def test_flap_thresholds_upper_limit_13(temp, expected):
    assert flap_for_deviation(temp, 13.0) == expected


def test_flap_custom_thresholds():
    assert flap_for_deviation(11.0, 10.0, thresholds=(0, 0.5, 2.0)) == 50


def feed(fan: FanController, series, step=5.0, t0=0.0):
    out = []
    for i, v in enumerate(series):
        out.append(fan.update(t0 + i * step, v))
    return out


def test_fan_on_when_rising_fast_and_off_after_30_min_stable():
    fan = FanController()
    rising = [10 + 1.0 * i for i in range(8)]  # +1 per 5 min = 0.2 /min > 0.12
    states = feed(fan, rising)
    assert states[-1] is True
    flat = [rising[-1]] * 12  # 60 min of flat
    states = feed(fan, flat, t0=40.0)
    assert states[0] is True  # does not switch off immediately
    assert states[-1] is False  # off after >= 30 min not rising
    # and it switched off no earlier than 30 min after stabilising
    first_off = states.index(False)
    assert first_off * 5 >= 30


def test_fan_ignores_sensor_noise():
    fan = FanController()
    noisy = [20, 21.2, 19.4, 20.8, 19.9, 21.0, 19.6, 20.5, 20.1, 20.9, 19.8, 20.3]
    assert not any(feed(fan, noisy))


def test_fan_stays_on_while_still_rising_and_while_falling_then_stabilises():
    fan = FanController()
    feed(fan, [0, 2, 4, 6, 8, 10, 12, 14])
    assert fan.fan_on
    falling = [14 - 2 * i for i in range(6)]  # scrubber working: index falls
    states = feed(fan, falling, t0=40.0)
    assert states[0] is True
    states = feed(fan, [4.0] * 10, t0=70.0)
    assert states[-1] is False


def test_fan_ignores_out_of_order_timestamps():
    fan = FanController()
    fan.update(10, 5)
    assert fan.update(10, 99) is False  # same timestamp: ignored
    assert fan.update(5, 99) is False


# ------------------------------------------------------------------ alert state machine


@pytest.mark.parametrize("risk,level", [(0, 0), (29.99, 0), (30, 1), (69.9, 1), (70, 2), (100, 2)])
def test_level_thresholds(risk, level):
    assert level_for_risk(risk) == level


def test_escalation_is_immediate_recovery_needs_hold():
    sm = AlertStateMachine(recovery_hold_s=15)
    assert sm.update(10, 0) is None
    t = sm.update(75, 10)
    assert t and t.current is Level.CRITICAL and t.escalated and t.newly_latched
    assert sm.update(20, 11) is None  # lower, but hold not elapsed
    assert sm.level is Level.CRITICAL
    assert sm.update(20, 20) is None  # 9 s of lower risk
    t = sm.update(20, 26.5)  # >= 15 s since 11
    assert t and t.current is Level.SAFE and not t.escalated


def test_recovery_hold_resets_if_risk_bounces_back_up():
    sm = AlertStateMachine(recovery_hold_s=15)
    sm.update(80, 0)
    sm.update(10, 5)  # start recovering
    sm.update(80, 10)  # back to critical level: hold timer must reset
    assert sm.update(10, 20) is None  # only 0 s into the new recovery window
    assert sm.level is Level.CRITICAL
    assert sm.update(10, 36) is not None


def test_critical_alarm_latches_until_acknowledged():
    sm = AlertStateMachine(recovery_hold_s=1)
    sm.update(90, 0)
    sm.update(5, 1)
    sm.update(5, 3)
    assert sm.level is Level.SAFE and sm.latched  # level recovered, buzzer still latched
    assert sm.acknowledge() is True and not sm.latched
    assert sm.acknowledge() is False


def test_relatch_after_ack_on_new_critical():
    sm = AlertStateMachine(recovery_hold_s=1)
    sm.update(90, 0)
    sm.acknowledge()
    assert sm.level is Level.CRITICAL and not sm.latched  # still critical, silenced
    sm.update(5, 1)
    sm.update(5, 3)
    t = sm.update(95, 10)
    assert t and t.newly_latched


def test_warning_to_critical_to_warning():
    sm = AlertStateMachine(recovery_hold_s=15)
    assert sm.update(40, 0).current is Level.WARNING
    assert sm.update(85, 5).current is Level.CRITICAL
    sm.update(45, 6)
    t = sm.update(45, 30)
    assert t.current is Level.WARNING
