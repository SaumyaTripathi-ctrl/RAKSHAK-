"""End-to-end quick training: split hygiene, leakage checks, model card, round trip."""

from __future__ import annotations

import json

import numpy as np
import pytest
from rakshak_ml import train as T
from rakshak_ml.dataset import generate_dataset
from rakshak_ml.features import FEATURES
from rakshak_ml.model import ModelBundle, ModelNotFoundError


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    out = tmp_path_factory.mktemp("artifacts")
    rc = T.main(["--out", str(out), "--quick", "--profiles", "real,demo"])
    assert rc == 0
    return out


def test_split_is_by_shipment_and_stratified():
    df = generate_dataset(10, "real", seed=3, stride=12)
    sp = T.split_by_shipment(df, seed=3)
    sets = [set(s.shipment_id) for s in (sp.train, sp.val, sp.test)]
    assert not (sets[0] & sets[1]) and not (sets[0] & sets[2]) and not (sets[1] & sets[2])
    assert len(sets[0]) + len(sets[1]) + len(sets[2]) == df.shipment_id.nunique()
    for part in (sp.train, sp.val, sp.test):
        assert part.food_type.nunique() == 5  # every food in every split
    assert (
        T.split_by_shipment(df, seed=3).test.shipment_id.tolist() == sp.test.shipment_id.tolist()
    )  # deterministic


def test_artifacts_written(trained):
    for profile in ("real", "demo"):
        d = trained / "models" / profile
        assert (d / "risk.joblib").exists() and (d / "rsl.joblib").exists()
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        assert meta["feature_columns"] == FEATURES and "SIMULATED" in meta["trained_on"]
    assert (trained / "training_report.json").exists() and (trained / "MODEL_CARD.md").exists()


def test_leakage_checks_pass_and_are_reported(trained):
    rep = json.loads((trained / "training_report.json").read_text(encoding="utf-8"))
    for profile in ("real", "demo"):
        checks = rep[profile]["leakage_checks"]
        assert {"no_shipment_in_two_splits", "cooling_status_absent", "shuffled_label_control",
                "no_single_feature_explains_label", "no_forbidden_feature_columns"} <= set(checks)  # fmt: skip
        assert all(c["ok"] for c in checks.values()), checks


def test_models_beat_baselines_on_heldout_shipments(trained):
    rep = json.loads((trained / "training_report.json").read_text(encoding="utf-8"))["real"]
    assert rep["risk"]["test"]["mae"] < rep["risk"]["baseline_mean_test"]["mae"] * 0.6
    assert rep["risk"]["test"]["r2"] > 0.6


def test_model_card_is_honest(trained):
    card = (trained / "MODEL_CARD.md").read_text(encoding="utf-8")
    assert "SIMULATED" in card and "TODO-verify" in card and "cooling_status" in card
    assert "demo" in card and "Not for real use" in card
    assert "Limitations" in card


def test_round_trip_predictions_are_sane(trained):
    bundle = ModelBundle.load(trained / "models", "real")
    df = generate_dataset(3, "real", seed=99, stride=10)
    risk, rsl = bundle.predict_frame(df)
    assert risk.min() >= 0 and risk.max() <= 100 and rsl.min() >= 0 and rsl.max() <= 240
    assert np.corrcoef(risk, df["risk_true"])[0, 1] > 0.8
    one = bundle.predict(df.iloc[0][FEATURES].to_dict())
    assert one.risk == pytest.approx(float(risk[0]))


def test_missing_model_is_a_clear_error(tmp_path):
    with pytest.raises(ModelNotFoundError, match="rakshak_ml.train"):
        ModelBundle.load(tmp_path, "real")


def test_bundle_refuses_forbidden_features(trained):
    b = ModelBundle.load(trained / "models", "real")
    with pytest.raises(ValueError, match="forbidden"):
        ModelBundle("real", b.risk_model, b.rsl_model, [*FEATURES, "cooling_status"], {})
    with pytest.raises(ValueError, match="unknown"):
        ModelBundle("real", b.risk_model, b.rsl_model, [*FEATURES, "made_up"], {})
