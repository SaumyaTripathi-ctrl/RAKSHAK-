"""Loading and running the trained model pairs (risk 0-100 + remaining safe life in hours)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np

from .features import FEATURES, FORBIDDEN_FEATURES
from .sim import RSL_CAP_H


class ModelNotFoundError(FileNotFoundError):
    pass


@dataclass(frozen=True)
class Prediction:
    risk: float  # 0-100
    rsl_hours: float  # remaining safe life if conditions stay as now (data hours)


class ModelBundle:
    def __init__(self, profile: str, risk_model, rsl_model, columns: list[str], meta: dict) -> None:
        bad = set(columns) & FORBIDDEN_FEATURES
        if bad:
            raise ValueError(f"model uses forbidden feature(s): {sorted(bad)}")
        unknown = set(columns) - set(FEATURES)
        if unknown:
            raise ValueError(f"model expects unknown feature(s): {sorted(unknown)}")
        self.profile, self.risk_model, self.rsl_model = profile, risk_model, rsl_model
        self.columns, self.meta = columns, meta
        scale = 24.0 if profile == "demo" else 1.0
        self.rsl_cap = RSL_CAP_H / scale

    @classmethod
    def load(cls, models_dir: str | Path, profile: str = "real") -> ModelBundle:
        d = Path(models_dir) / profile
        meta_path = d / "meta.json"
        if not meta_path.exists():
            raise ModelNotFoundError(
                f"no '{profile}' model in {d} - run `python -m rakshak_ml.train`"
            )
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return cls(
            profile,
            joblib.load(d / "risk.joblib"),
            joblib.load(d / "rsl.joblib"),
            meta["feature_columns"],
            meta,
        )

    def predict_matrix(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        risk = np.clip(self.risk_model.predict(x), 0.0, 100.0)
        rsl = np.clip(self.rsl_model.predict(x), 0.0, self.rsl_cap)
        return risk, rsl

    def predict_frame(self, df) -> tuple[np.ndarray, np.ndarray]:
        return self.predict_matrix(df[self.columns].to_numpy(dtype=float))

    def predict(self, feats: dict[str, float]) -> Prediction:
        x = np.array([[float(feats[c]) for c in self.columns]])
        risk, rsl = self.predict_matrix(x)
        return Prediction(float(risk[0]), float(rsl[0]))
