"""Feature engine (hand-computed) and simulator (determinism + physical sanity)."""

from __future__ import annotations

import numpy as np
import pytest
from rakshak_ml.bands import get_band
from rakshak_ml.dataset import PROFILES, generate_dataset, rows_to_frame
from rakshak_ml.features import FEATURES, FORBIDDEN_FEATURES, FeatureEngine, Reading
from rakshak_ml.sim import RSL_CAP_H, ShipmentSim, SimConfig, simulate

# ------------------------------------------------------------------ features


def test_feature_list_is_clean():
    assert len(FEATURES) == len(set(FEATURES))
    assert not set(FEATURES) & FORBIDDEN_FEATURES
    assert "cooling_status" not in FEATURES
    for required in (
        "ethylene_index",
        "cumulative_ethylene_exposure",
        "shock_g",
        "flap_position",
        "scrubber_on",
    ):
        assert required in FEATURES


def test_features_hand_computed():
    band = get_band("mango")  # 10-13 C, RH 85-90
    eng = FeatureEngine(band)
    f0 = eng.update(Reading(t=0, temperature=12.0, humidity=88, ethylene_index=10))
    assert f0["temperature_deviation"] == 0 and f0["time_outside_temp_range"] == 0
    assert f0["temperature_rate_of_change"] == 0 and f0["elapsed_minutes"] == 0

    f1 = eng.update(
        Reading(
            t=600,
            temperature=15.0,
            humidity=80,
            ethylene_index=16,
            shock_g=0.5,
            flap_position=50,
            scrubber_on=1,
        )
    )
    assert f1["temperature_deviation"] == 2.0 and f1["humidity_deviation"] == 5.0
    assert f1["temperature_rate_of_change"] == pytest.approx(0.3)  # 3 C / 10 min
    assert f1["ethylene_rate_of_change"] == pytest.approx(0.6)
    assert f1["time_outside_temp_range"] == 10 and f1["cumulative_temp_exposure"] == pytest.approx(
        20.0
    )
    assert f1["cumulative_humidity_exposure"] == pytest.approx(50.0)
    assert f1["temperature_excursion_count"] == 1 and f1["time_since_first_excursion"] == 0
    assert f1["cumulative_ethylene_exposure"] == pytest.approx(160.0)
    assert f1["shock_count"] == 1 and f1["max_shock"] == 0.5
    assert f1["flap_position"] == 50 and f1["scrubber_on"] == 1 and f1["elapsed_minutes"] == 10

    f2 = eng.update(Reading(t=1200, temperature=11.0, humidity=88, ethylene_index=12))
    assert f2["time_outside_temp_range"] == 10  # back inside: no more accumulation
    assert f2["max_temp_deviation"] == 2.0 and f2["max_ethylene_index"] == 16
    assert f2["time_since_first_excursion"] == 10

    f3 = eng.update(Reading(t=1800, temperature=14.0, humidity=88))
    assert f3["temperature_excursion_count"] == 2  # a second, separate excursion


def test_long_gaps_are_not_integrated_as_exposure():
    eng = FeatureEngine(get_band("milk"))
    eng.update(Reading(t=0, temperature=3, humidity=50))
    f = eng.update(Reading(t=6 * 3600, temperature=10, humidity=50))  # 6 h gap, now warm
    assert f["time_outside_temp_range"] == 60  # capped at 60 min, not 360


def test_out_of_order_readings_do_not_go_negative():
    eng = FeatureEngine(get_band("milk"))
    eng.update(Reading(t=600, temperature=3, humidity=50))
    f = eng.update(Reading(t=300, temperature=9, humidity=50))
    assert f["time_outside_temp_range"] == 0 and f["temperature_rate_of_change"] == 0


# ------------------------------------------------------------------ simulator


def test_simulation_is_deterministic():
    a = simulate("banana", 24, seed=7)
    b = simulate("banana", 24, seed=7)
    c = simulate("banana", 24, seed=8)
    assert a == b and a != c


def test_row_schema_and_ranges():
    rows = simulate("tomato", 12, seed=3)
    assert len(rows) == 12 * 12
    for r in rows:
        assert 0 <= r["ethylene_index"] <= 100 and 20 <= r["humidity"] <= 100
        assert 0 <= r["risk_true"] <= 100 and 0 <= r["rsl_true_h"] <= RSL_CAP_H
        assert r["flap_position"] in (0, 25, 50, 100) and r["scrubber_on"] in (0, 1)
        assert r["shock_g"] >= 0


def test_consumed_life_never_decreases():
    c = [r["consumed"] for r in simulate("mango", 48, seed=11)]
    assert all(b >= a for a, b in zip(c, c[1:], strict=False))


def _run(food="mango", seed=1, hours=24, **kw):
    cfg = dict(
        heat_excursions=0,
        has_pcm=False,
        has_scrubber=False,
        mixed_load_ethylene=0.0,
        reading_spikes=[],
    )
    cfg.update(kw)
    return ShipmentSim(SimConfig(food, hours, seed=seed, **cfg))


def test_heat_makes_spoilage_faster_than_cold_room():
    cold = _run(ambient_override=get_band("mango").mid_temp)
    hot = _run(ambient_override=34.0)
    cold.life_mult = hot.life_mult = 1.0
    rc, rh = cold.run(), hot.run()
    assert rh[-1]["temperature"] > rc[-1]["temperature"] + 5
    assert rh[-1]["risk_true"] > rc[-1]["risk_true"] + 10


def test_heat_excursion_raises_crate_temperature():
    calm = _run(ambient_override=12.0)
    hot = _run(ambient_override=12.0)
    hot.excursions = [(4.0, 14.0, 20.0)]
    tc = max(r["temperature"] for r in calm.run())
    th = max(r["temperature"] for r in hot.run())
    assert th > tc + 3


def test_pcm_flap_cools_and_depletes():
    def run(pcm: bool, cap: float):
        sim = _run(hours=48, has_pcm=pcm, ambient_override=32.0)
        sim.pcm_cap0 = cap
        return [r["temperature"] for r in sim.run()]

    none, good, empty = run(False, 80.0), run(True, 80.0), run(True, 1.0)
    late = slice(300, 576)  # last ~23 h
    assert np.mean(good[late]) < np.mean(none[late]) - 8  # PCM holds the load near its band
    assert (
        abs(np.mean(empty[late]) - np.mean(none[late])) < 1.0
    )  # an exhausted PCM pack does nothing
    assert np.mean(good[:96]) < np.mean(none[:96])  # and it helps from the start


def test_scrubber_lowers_ethylene_when_ripening():
    kw = dict(ambient_override=28.0, mixed_load_ethylene=0.0)
    off, on = (
        _run("banana", seed=5, hours=72, has_scrubber=False, **kw),
        _run("banana", seed=5, hours=72, has_scrubber=True, **kw),
    )
    off.life_mult = on.life_mult = 1.0
    a, b = off.run(), on.run()
    assert max(r["scrubber_on"] for r in b) == 1 and max(r["scrubber_on"] for r in a) == 0
    assert (
        np.mean([r["ethylene_index"] for r in b[-96:]])
        < np.mean([r["ethylene_index"] for r in a[-96:]]) - 5
    )
    assert b[-1]["consumed"] < a[-1]["consumed"]  # and it saves shelf life


def test_ethylene_index_can_fall_when_scrubber_runs():
    rows = _run("banana", seed=5, hours=72, has_scrubber=True, ambient_override=28.0).run()
    eth = [r["ethylene_index"] for r in rows]
    fan_first = next(i for i, r in enumerate(rows) if r["scrubber_on"])
    # with the scrubber running, the index stops climbing: it stays far below the no-scrubber peak
    off = [
        r["ethylene_index"]
        for r in _run("banana", seed=5, hours=72, has_scrubber=False, ambient_override=28.0).run()
    ]
    assert max(eth) < max(off) - 10
    assert max(eth[fan_first:]) > 0


def test_non_ethylene_foods_have_no_ethylene_signal():
    milk = simulate("milk", 24, seed=2)
    assert max(r["ethylene_index"] for r in milk) < 15
    assert max(r["scrubber_on"] for r in milk) == 0


def test_milk_is_not_chilling_injured_but_mango_is():
    cold = dict(ambient_override=3.0)
    mango, milk = _run("mango", **cold), _run("milk", **cold)
    rm = mango.rate_factor(5.0, 88, 0, 0)
    assert rm > 1.5  # below 10 C: chilling injury
    assert milk.rate_factor(1.0, 60, 0, 0) <= 1.0


def test_brief_reading_spike_does_not_change_ground_truth():
    a = _run(ambient_override=12.0, reading_spikes=[])
    b = _run(ambient_override=12.0, reading_spikes=[(300, 20, 8)])
    a.life_mult = b.life_mult = 1.0
    ra, rb = a.run(), b.run()
    assert (
        max(r["temperature"] for r in rb) > max(r["temperature"] for r in ra) + 5
    )  # sensor sees it
    assert rb[-1]["consumed"] == pytest.approx(ra[-1]["consumed"], rel=0.02)  # the load does not


def test_time_scale_compresses_physics():
    real = _run(ambient_override=30.0)
    demo = ShipmentSim(
        SimConfig("mango", 1.0, step_min=1.0, time_scale=24.0, seed=1, heat_excursions=0, has_pcm=False,
                  has_scrubber=False, mixed_load_ethylene=0.0, reading_spikes=[], ambient_override=30.0)
    )  # fmt: skip
    real.life_mult = demo.life_mult = 1.0
    rr = real.run()
    rd = demo.run()  # 1 data hour = 24 physical hours
    assert rd[-1]["consumed"] == pytest.approx(rr[-1]["consumed"], rel=0.25)


def test_dataset_frame_has_features_labels_and_split_keys():
    df = generate_dataset(2, "real", seed=1, stride=12)
    assert set(FEATURES) <= set(df.columns)
    assert {"risk_true", "rsl_true_h", "shipment_id", "food_type"} <= set(df.columns)
    assert df.shipment_id.nunique() == 10 and set(df.food_type) == {
        "mango",
        "banana",
        "tomato",
        "leafy_vegetables",
        "milk",
    }
    assert PROFILES["demo"]["time_scale"] == 24


def test_rows_to_frame_matches_engine():
    rows = simulate("mango", 6, seed=4)
    df = rows_to_frame(rows)
    eng = FeatureEngine(get_band("mango"))
    last = None
    for r in rows:
        last = eng.update(Reading(r["t_min"] * 60, r["temperature"], r["humidity"], r["ethylene_index"], r["shock_g"],
                                  r["external_temperature"], r["external_humidity"], r["rain_probability"],
                                  r["wind_speed"], r["flap_position"], r["scrubber_on"]))  # fmt: skip
    for k, v in last.items():
        assert df.iloc[-1][k] == pytest.approx(v)
