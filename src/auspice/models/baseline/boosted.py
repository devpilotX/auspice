"""The gradient boosted baseline.

Section 6.8: XGBoost establishes signal and a floor. Section 7.2 is blunt about why it is here and
not a neural network: on a few thousand rows of tabular data, gradient boosting still wins
decisively, and a neural network would be worse, slower and unexplainable.

It stays in the system permanently even after the hierarchical model exists, because it is the honest
benchmark the Bayesian model has to beat. If the Bayesian model never beats it, section 6.8 says ship
the simpler one, and that instruction is only followable if both are measured on every run.

Two details that matter.

**Missing values are passed through.** XGBoost learns a default direction per split for NaN, which is
strictly better than imputing a mean and pretending we knew. Nothing is zero filled here.

**The intervals are quantile based, not made up.** A boosted classifier has no posterior, so the
80 percent interval comes from the spread of predictions across bootstrap resamples. It is wider and
less principled than the hierarchical model's credible interval, and it is labelled as such.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import polars as pl

from auspice.logging import get_logger

log = get_logger(__name__, _stage="models")

MODEL_KIND = "gradient_boosted"
MODEL_VERSION = "1.0.0"

BOOTSTRAP_ROUNDS = 40


def default_params(n_rows: int) -> dict[str, Any]:
    """Hyperparameters scaled to the sample size.

    Not tuned by search. On a few hundred rows a hyperparameter search overfits the validation split
    and produces a number that will not hold, so the parameters are set conservatively by rule:
    shallow trees, strong regularisation, and a learning rate low enough that the ensemble is not
    dominated by its first few trees.
    """
    return {
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "max_depth": 2 if n_rows < 300 else 3 if n_rows < 1500 else 4,
        "min_child_weight": max(4.0, n_rows / 60.0),
        "learning_rate": 0.05,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "reg_lambda": 4.0,
        "reg_alpha": 0.5,
        "n_estimators": 300,
        "tree_method": "hist",
        "n_jobs": 4,
        "random_state": 20260827,
    }


@dataclass(slots=True)
class BoostedModel:
    feature_columns: list[str]
    params: dict[str, Any] = field(default_factory=dict)
    booster: Any = None
    ensemble: list[Any] = field(default_factory=list)
    n_train: int = 0
    base_rate: float = 0.5

    def fit(
        self, dataset_frame: pl.DataFrame, *, feature_columns: list[str] | None = None
    ) -> BoostedModel:
        from xgboost import XGBClassifier

        columns = feature_columns or self.feature_columns
        self.feature_columns = columns
        x = dataset_frame.select(columns).to_numpy().astype(np.float64)
        y = dataset_frame.select("approved").to_numpy().ravel().astype(np.int8)
        self.n_train = len(y)
        self.base_rate = float(y.mean()) if len(y) else 0.5

        if len(np.unique(y)) < 2:
            # One class only. A boosted model cannot learn anything and would report perfect
            # training accuracy, so it declines and the caller falls back to the base rate.
            log.warning("boosted model declined: only one outcome class present", rows=self.n_train)
            self.booster = None
            return self

        self.params = default_params(self.n_train)
        self.booster = XGBClassifier(**self.params)
        self.booster.fit(x, y, verbose=False)

        # Bootstrap ensemble for intervals. Fewer trees each, because these exist to measure
        # variance rather than to predict.
        rng = np.random.default_rng(self.params["random_state"])
        interval_params = {**self.params, "n_estimators": 120}
        self.ensemble = []
        for _ in range(BOOTSTRAP_ROUNDS):
            index = rng.integers(0, len(y), size=len(y))
            if len(np.unique(y[index])) < 2:
                continue
            member = XGBClassifier(**interval_params)
            member.fit(x[index], y[index], verbose=False)
            self.ensemble.append(member)

        log.info(
            "boosted model fitted",
            rows=self.n_train,
            features=len(columns),
            depth=self.params["max_depth"],
            ensemble=len(self.ensemble),
        )
        return self

    def predict(self, frame: pl.DataFrame) -> np.ndarray:
        if self.booster is None:
            return np.full(frame.height, self.base_rate, dtype=np.float64)
        x = frame.select(self.feature_columns).to_numpy().astype(np.float64)
        return np.asarray(self.booster.predict_proba(x)[:, 1], dtype=np.float64)

    def predict_interval(self, frame: pl.DataFrame, *, level: float = 0.80) -> np.ndarray:
        """Bootstrap interval, shape (n, 2).

        Labelled a bootstrap interval rather than a credible interval everywhere it surfaces,
        because it is not one, and calling it one would be the kind of quiet overstatement that
        makes a published calibration record indefensible.
        """
        if not self.ensemble:
            point = self.predict(frame)
            return np.stack([point, point], axis=1)
        x = frame.select(self.feature_columns).to_numpy().astype(np.float64)
        draws = np.stack([m.predict_proba(x)[:, 1] for m in self.ensemble], axis=0)
        lower = np.quantile(draws, (1.0 - level) / 2.0, axis=0)
        upper = np.quantile(draws, 1.0 - (1.0 - level) / 2.0, axis=0)
        return np.stack([lower, upper], axis=1)

    def importances(self) -> dict[str, float]:
        if self.booster is None:
            return {}
        gains = self.booster.feature_importances_
        total = float(gains.sum()) or 1.0
        return {
            name: round(float(g) / total, 6)
            for name, g in sorted(
                zip(self.feature_columns, gains, strict=True), key=lambda p: -p[1]
            )
        }

    def shap_values(self, frame: pl.DataFrame) -> np.ndarray | None:
        """SHAP contributions, for the drivers table.

        Section 6.10: driver weights come from the model, not from a language model's opinion about
        which factors matter. Returns None if SHAP cannot run, and the caller falls back to gain
        importances with that fact recorded.
        """
        if self.booster is None:
            return None
        try:
            import shap

            explainer = shap.TreeExplainer(self.booster)
            x = frame.select(self.feature_columns).to_numpy().astype(np.float64)
            values = explainer.shap_values(x)
            if isinstance(values, list):
                values = values[-1]
            return np.asarray(values, dtype=np.float64)
        except Exception as exc:
            log.warning("shap unavailable", error=str(exc))
            return None
