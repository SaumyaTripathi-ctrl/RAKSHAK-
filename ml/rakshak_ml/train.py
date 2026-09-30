"""Train the real + demo Random Forest pairs on SIMULATED shipments and write a report + model card.

    python -m rakshak_ml.train [--out ml/artifacts] [--per-food 200] [--seed 42] [--profiles real,demo] [--quick]

Outputs ``<out>/models/<profile>/{risk,rsl}.joblib + meta.json``, ``<out>/training_report.json`` and
``<out>/MODEL_CARD.md``. Model binaries are never committed; the report and the card are.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score

from .alert import Level, level_for_risk
from .bands import get_band, load_bands
from .dataset import PROFILES, generate_dataset, rows_to_frame
from .features import FEATURES, FORBIDDEN_FEATURES
from .model import ModelBundle
from .sim import ShipmentSim, SimConfig

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "artifacts"

RF_PARAMS = dict(n_estimators=80, max_depth=14, min_samples_leaf=20, max_features=0.5, n_jobs=-1)


@dataclass
class Split:
    train: pd.DataFrame
    val: pd.DataFrame
    test: pd.DataFrame


def split_by_shipment(df: pd.DataFrame, seed: int, frac=(0.70, 0.15, 0.15)) -> Split:
    """Stratified by food type; a shipment is wholly in one split (no row-level leakage across time)."""
    rng = np.random.default_rng(seed)
    assign: dict[str, str] = {}
    for _food, g in df.groupby("food_type"):
        ids = sorted(g["shipment_id"].unique())
        rng.shuffle(ids)
        n = len(ids)
        n_tr, n_va = int(round(n * frac[0])), int(round(n * frac[1]))
        for k, sid in enumerate(ids):
            assign[sid] = "train" if k < n_tr else "val" if k < n_tr + n_va else "test"
    part = df["shipment_id"].map(assign)
    return Split(df[part == "train"], df[part == "val"], df[part == "test"])


def _metrics(y, p) -> dict:
    return {
        "mae": round(float(mean_absolute_error(y, p)), 3),
        "r2": round(float(r2_score(y, p)), 4),
    }


def _levels(x) -> np.ndarray:
    return np.array([int(level_for_risk(v)) for v in x])


def leakage_checks(
    split: Split, cols: list[str], y_test_risk, rf_test_r2: float, seed: int
) -> dict:
    """Automated guards. Each entry: {ok, detail}."""
    checks: dict[str, dict] = {}
    tr, va, te = (set(s["shipment_id"]) for s in (split.train, split.val, split.test))
    overlap = (tr & va) | (tr & te) | (va & te)
    checks["no_shipment_in_two_splits"] = {
        "ok": not overlap,
        "detail": f"{len(overlap)} shared shipments",
    }
    bad = sorted(set(cols) & FORBIDDEN_FEATURES)
    checks["no_forbidden_feature_columns"] = {"ok": not bad, "detail": ", ".join(bad) or "none"}
    checks["cooling_status_absent"] = {
        "ok": "cooling_status" not in cols,
        "detail": "the MedRakshak leak",
    }
    checks["features_are_exactly_the_declared_list"] = {
        "ok": cols == FEATURES,
        "detail": f"{len(cols)} features",
    }

    # Any single feature that (nearly) reproduces the label on its own would be a red flag.
    worst = ("", -1.0)
    sub = split.train.sample(min(len(split.train), 20000), random_state=seed)
    for c in cols:
        x = sub[[c]].to_numpy(dtype=float)
        if np.ptp(x) == 0:
            continue
        r2 = LinearRegression().fit(x, sub["risk_true"]).score(x, sub["risk_true"])
        if r2 > worst[1]:
            worst = (c, float(r2))
    checks["no_single_feature_explains_label"] = {
        "ok": worst[1] < 0.95,
        "detail": f"best linear single-feature R2 = {worst[1]:.3f} ({worst[0]})",
    }

    # Label-shuffle control: the same model on shuffled labels must be useless.
    rng = np.random.default_rng(seed)
    y_shuf = rng.permutation(split.train["risk_true"].to_numpy())
    m = RandomForestRegressor(**{**RF_PARAMS, "n_estimators": 20}, random_state=seed)
    m.fit(split.train[cols].to_numpy(dtype=float), y_shuf)
    shuf_r2 = r2_score(y_test_risk, m.predict(split.test[cols].to_numpy(dtype=float)))
    checks["shuffled_label_control"] = {
        "ok": shuf_r2 < 0.05,
        "detail": f"R2 on test with shuffled training labels = {shuf_r2:.3f} (real model: {rf_test_r2:.3f})",
    }
    return checks


def scenario_eval(bundle: ModelBundle, profile: str) -> dict:
    """Scripted what-if shipments in a cold room: nothing happens / a brief reading spike / a long heat event."""
    spec = PROFILES[profile]
    ts, step = spec["time_scale"], spec["step_min"]
    dur = 48.0 if profile == "real" else 3.0  # data hours
    out = {}
    scenarios = {
        "steady_in_band": dict(reading_spikes=[], exc=[]),
        "short_spike_20min": dict(reading_spikes=[(dur * 60 * 0.4, 20.0, 8.0)], exc=[]),
        "long_heat_event": dict(
            reading_spikes=[], exc=[(dur * ts * 0.25, dur * ts * 0.25 + 9.0, 22.0)]
        ),
    }
    for name, sc in scenarios.items():
        maxima, finals = [], []
        for food in ("mango", "banana", "tomato", "milk", "leafy_vegetables"):
            band = get_band(food)
            for s_ in range(6):
                sim = ShipmentSim(
                    SimConfig(
                        food, dur, step_min=step, time_scale=ts, seed=900 + s_,
                        heat_excursions=0, has_pcm=False, has_scrubber=False, mixed_load_ethylene=0.0,
                        ambient_override=band.mid_temp, reading_spikes=sc["reading_spikes"],
                    )
                )  # fmt: skip
                sim.life_mult = 1.0
                sim.excursions = list(sc["exc"])
                df = rows_to_frame(sim.run())
                risk, _ = bundle.predict_frame(df)
                maxima.append(float(risk.max()))
                finals.append(float(risk[-1]))
        out[name] = {
            "mean_max_risk": round(float(np.mean(maxima)), 1),
            "mean_final_risk": round(float(np.mean(finals)), 1),
            "share_reaching_warning": round(float(np.mean([m >= 30 for m in maxima])), 2),
            "share_reaching_critical": round(float(np.mean([m >= 70 for m in maxima])), 2),
        }
    return out


def train_profile(
    profile: str, out: Path, per_food: int, seed: int, stride: int, log=print
) -> dict:
    t0 = time.time()
    log(f"[{profile}] simulating {per_food} shipments x {len(load_bands())} foods ...")
    data = generate_dataset(per_food, profile, seed=seed, stride=stride)
    split = split_by_shipment(data, seed)
    log(f"[{profile}] rows: train={len(split.train)} val={len(split.val)} test={len(split.test)}")

    cols = list(FEATURES)
    x_tr, x_va, x_te = (s[cols].to_numpy(dtype=float) for s in (split.train, split.val, split.test))
    report: dict = {
        "profile": profile,
        "rows": {"train": len(split.train), "val": len(split.val), "test": len(split.test)},
    }

    models = {}
    for target, name in (("risk_true", "risk"), ("rsl_true_h", "rsl")):
        rf = RandomForestRegressor(**RF_PARAMS, random_state=seed).fit(x_tr, split.train[target])
        models[name] = rf
        base_mean = np.full(len(split.test), split.train[target].mean())
        lin_cols = ["temperature_deviation", "cumulative_temp_exposure", "time_outside_temp_range"]
        lin = LinearRegression().fit(split.train[lin_cols], split.train[target])
        p_test = rf.predict(x_te)
        report[name] = {
            "val": _metrics(split.val[target], rf.predict(x_va)),
            "test": _metrics(split.test[target], p_test),
            "baseline_mean_test": _metrics(split.test[target], base_mean),
            "baseline_linear_3feat_test": _metrics(
                split.test[target], lin.predict(split.test[lin_cols])
            ),
        }
        if name == "rsl":
            cap = 240.0 / (24.0 if profile == "demo" else 1.0)
            report[name]["test"]["mae_when_true_rsl_below_half_cap"] = round(
                float(mean_absolute_error(
                    split.test.loc[split.test[target] < cap / 2, target],
                    np.clip(p_test, 0, cap)[(split.test[target] < cap / 2).to_numpy()],
                )), 3,
            )  # fmt: skip

    risk_pred = np.clip(models["risk"].predict(x_te), 0, 100)
    true_lv, pred_lv = _levels(split.test["risk_true"]), _levels(risk_pred)
    report["alert_levels"] = {
        "accuracy": round(float((true_lv == pred_lv).mean()), 4),
        "critical_recall": round(float((pred_lv[true_lv == 2] == 2).mean()) if (true_lv == 2).any() else float("nan"), 4),
        "critical_precision": round(float((true_lv[pred_lv == 2] == 2).mean()) if (pred_lv == 2).any() else float("nan"), 4),
        "share_true": {Level(i).name: round(float((true_lv == i).mean()), 4) for i in range(3)},
    }  # fmt: skip
    report["per_food_risk_test_mae"] = {
        f: round(float(mean_absolute_error(g["risk_true"], np.clip(models["risk"].predict(g[cols].to_numpy(dtype=float)), 0, 100))), 2)
        for f, g in split.test.groupby("food_type")
    }  # fmt: skip
    imp = sorted(zip(cols, models["risk"].feature_importances_, strict=True), key=lambda kv: -kv[1])
    report["top_features_risk"] = [
        {"feature": k, "importance": round(float(v), 4)} for k, v in imp[:10]
    ]
    report["leakage_checks"] = leakage_checks(
        split, cols, split.test["risk_true"], report["risk"]["test"]["r2"], seed
    )

    d = out / "models" / profile
    d.mkdir(parents=True, exist_ok=True)
    for name, m in models.items():
        joblib.dump(m, d / f"{name}.joblib", compress=3)
    data_hash = hashlib.sha256(
        pd.util.hash_pandas_object(split.test[cols + ["risk_true"]]).values.tobytes()
    ).hexdigest()[:16]
    meta = {
        "profile": profile,
        "feature_columns": cols,
        "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "seed": seed,
        "per_food": per_food,
        "stride": stride,
        "trained_on": "SIMULATED data (rakshak_ml.sim) - not validated against real spoilage outcomes",
        "rf_params": RF_PARAMS,
        "test_set_hash": data_hash,
        "metrics": {k: report[k]["test"] for k in ("risk", "rsl")},
    }
    (d / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    bundle = ModelBundle.load(out / "models", profile)
    report["scenarios"] = scenario_eval(bundle, profile)
    report["seconds"] = round(time.time() - t0, 1)
    log(f"[{profile}] risk test R2={report['risk']['test']['r2']} MAE={report['risk']['test']['mae']}; "
        f"rsl R2={report['rsl']['test']['r2']}; levels acc={report['alert_levels']['accuracy']}  ({report['seconds']}s)")  # fmt: skip
    return report


def render_model_card(reports: dict[str, dict], args: dict) -> str:
    bands = load_bands()
    L = []
    w = L.append
    w("# Rakshak spoilage model card")
    w("")
    w(
        "> **Trained entirely on SIMULATED shipments.** Nothing here has been validated against real spoilage outcomes."
    )
    w("> The FPO pilot is meant to collect real outcomes to retrain and validate these models.")
    w("")
    w(f"Generated {datetime.now(UTC).isoformat(timespec='seconds')} by `python -m rakshak_ml.train` "
      f"(seed {args['seed']}, {args['per_food']} simulated shipments per food type and profile).")  # fmt: skip
    w("")
    w("## What the models predict")
    w("")
    w("| Output | Meaning |")
    w("|---|---|")
    w("| `spoilage_risk` (0-100) | fraction of shelf life consumed plus a small term for the *current* degradation rate. "
      "SAFE < 30, WARNING 30-70, CRITICAL >= 70. Driven by accumulated exposure, so a short spike does not alarm but a long excursion escalates. |")  # fmt: skip
    w(
        "| `remaining_safe_life_hours` | hours until the food is spoiled **if conditions stay as they are now**, capped at 240 h (real profile). |"
    )
    w("")
    w("Both are defined by the simulator's hidden quality model (see `ml/rakshak_ml/sim.py`). They are *assumptions*, "
      "not measurements: per-food Q10 factors, chilling-injury, humidity, ethylene, over-ripeness and shock-damage terms, "
      "and a nominal shelf life per food that is a simulator assumption.")  # fmt: skip
    w("")
    w("## Two model pairs")
    w("")
    w(
        "* **real** - physical time scale; trips of 1-4 days, a record every 5 minutes. Use this for anything real."
    )
    w("* **demo** - the same physics with time compressed 24x (trips of 1.5-5 h, a record every minute), so the risk moves "
      "visibly in a short live demo. **Not for real use.**")  # fmt: skip
    w("")
    w("Each pair is two scikit-learn `RandomForestRegressor`s (risk, remaining life). "
      f"Hyper-parameters: `{json.dumps(RF_PARAMS)}`.")  # fmt: skip
    w("")
    w("## Features (" + str(len(FEATURES)) + ")")
    w("")
    w("`" + "`, `".join(FEATURES) + "`")
    w("")
    w("Same code path in training and serving (`rakshak_ml.features.FeatureEngine`). `cooling_status` is **not** a feature "
      "(it leaked the label in the MedRakshak demo model); actuator state is only `flap_position` and `scrubber_on`.")  # fmt: skip
    w("")
    w("## Food bands")
    w("")
    w("| Food | Temp band (C) | RH band (%) | Ethylene sens./prod. | Source | Status |")
    w("|---|---|---|---|---|---|")
    for b in bands.values():
        w(f"| {b.food_type} | {b.min_temp}-{b.max_temp} | {b.min_rh}-{b.max_rh} | "
          f"{'yes' if b.ethylene_sensitive else 'no'}/{'yes' if b.ethylene_producer else 'no'} | {b.source} | **{b.verification_status}** |")  # fmt: skip
    w("")
    w("## Evaluation (held-out *shipments*, never seen in training)")
    w("")
    for profile, rep in reports.items():
        w(f"### {profile} profile")
        w("")
        w(f"Rows: train {rep['rows']['train']:,} / val {rep['rows']['val']:,} / test {rep['rows']['test']:,} "
          f"(split by shipment, stratified by food type).")  # fmt: skip
        w("")
        w(
            "| Target | Model MAE | Model R2 | Mean-baseline MAE | 3-feature linear MAE | 3-feature linear R2 |"
        )
        w("|---|---|---|---|---|---|")
        for name, label in (("risk", "risk (0-100)"), ("rsl", "remaining life (h)")):
            r = rep[name]
            w(f"| {label} | {r['test']['mae']} | {r['test']['r2']} | {r['baseline_mean_test']['mae']} | "
              f"{r['baseline_linear_3feat_test']['mae']} | {r['baseline_linear_3feat_test']['r2']} |")  # fmt: skip
        a = rep["alert_levels"]
        w("")
        w(f"Alert-level accuracy {a['accuracy']:.1%}; CRITICAL recall {a['critical_recall']:.1%}, "
          f"CRITICAL precision {a['critical_precision']:.1%}. True level mix: {a['share_true']}.")  # fmt: skip
        w("")
        w(
            "Risk MAE per food: "
            + ", ".join(f"{k} {v}" for k, v in rep["per_food_risk_test_mae"].items())
            + "."
        )
        w("")
        w("Scripted scenarios in a cold room (no PCM, no scrubber, batch quality = nominal):")
        w("")
        w("| Scenario | mean max risk | reaches WARNING | reaches CRITICAL |")
        w("|---|---|---|---|")
        for k, v in rep["scenarios"].items():
            w(
                f"| {k} | {v['mean_max_risk']} | {v['share_reaching_warning']:.0%} | {v['share_reaching_critical']:.0%} |"
            )
        w("")
        w(
            "Top risk features: "
            + ", ".join(
                f"`{f['feature']}` ({f['importance']:.2f})" for f in rep["top_features_risk"][:6]
            )
            + "."
        )
        w("")
        w("Leakage checks:")
        w("")
        for k, v in rep["leakage_checks"].items():
            w(f"* {'PASS' if v['ok'] else '**FAIL**'} `{k}` - {v['detail']}")
        w("")
    w("## Limitations")
    w("")
    w("* Labels come from the simulator's own quality model, so high scores measure how well the forest learned *that* model, "
      "not how well it predicts real spoilage. Real validation is future work (FPO pilot).")  # fmt: skip
    w(
        "* Food bands are placeholders marked TODO-verify; the nominal shelf lives are simulator assumptions."
    )
    w("* The simulated ethylene index tracks concentration with a lag; real indicator strips are largely irreversible and need "
      "per-batch lab calibration against a reference sensor (pending).")  # fmt: skip
    w("* The crate is represented by the mean tag temperature; per-tag spread is not modelled.")
    w("* Remaining life assumes conditions persist; it does not forecast future excursions.")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--per-food", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--profiles", default="real,demo")
    ap.add_argument("--stride", type=int, default=4, help="keep every Nth row of each shipment")
    ap.add_argument(
        "--quick", action="store_true", help="tiny run for tests/CI (per-food 12, stride 6)"
    )
    a = ap.parse_args(argv)
    if a.quick:
        a.per_food, a.stride = 12, 6
    a.out.mkdir(parents=True, exist_ok=True)
    reports = {}
    for profile in a.profiles.split(","):
        reports[profile] = train_profile(profile, a.out, a.per_food, a.seed, a.stride)
    (a.out / "training_report.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
    (a.out / "MODEL_CARD.md").write_text(render_model_card(reports, vars(a)), encoding="utf-8")
    failed = [k for r in reports.values() for k, v in r["leakage_checks"].items() if not v["ok"]]
    if failed:
        print("LEAKAGE CHECK FAILED:", failed, file=sys.stderr)
        return 1
    print(f"wrote models, training_report.json and MODEL_CARD.md to {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
