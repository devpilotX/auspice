"""The kill test.

Section 12, days 15 to 16, and section 14 risk 1. This is the test that decides whether the company
is real. It trains on decisions before a cutoff and predicts held out decisions after it, then reports
the Brier score against the base rate benchmark, expected calibration error, interval coverage and
abstention precision.

Three properties of this module are the whole point of it.

**It refuses to answer on a sample too small to support an answer.** Below the floors in
``thresholds.py`` it returns ``INSUFFICIENT DATA`` and no metrics. A verdict computed on twelve
decisions would be quoted by someone, and it would be a coin flip wearing a number.

**The thresholds are imported, not written here.** Anyone relaxing a pass condition has to edit a file
whose only job is to hold pass conditions, which makes it a one line visible diff rather than a tweak
buried in a hundred lines of evaluation code.

**The verdict is computed before it is printed, and nothing rounds in the favourable direction.**
Metrics are rounded for display only, after the comparison.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import polars as pl
from sqlalchemy.engine import Connection

from auspice.logging import get_logger
from auspice.models.baseline.base_rate import BaseRateModel
from auspice.models.baseline.boosted import BoostedModel
from auspice.models.dataset import Dataset, load_dataset
from auspice.models.eval.metrics import (
    IsotonicCalibrator,
    PlattCalibrator,
    ReliabilityCurve,
    abstention_precision,
    auc,
    binned_interval_coverage,
    brier_score,
    brier_skill_score,
    choose_calibrator,
    log_loss,
    reliability_curve,
)
from auspice.models.eval.thresholds import (
    ABSTAIN_MAX_COMPARABLES,
    ABSTAIN_MAX_INTERVAL_WIDTH,
    ABSTAIN_MAX_POOLING_WEIGHT,
    COVERAGE_BAND,
    MAX_ECE,
    MIN_ABSTENTION_PRECISION,
    MIN_AUC,
    MIN_BRIER_SKILL,
    MIN_DEPTH_FOR_CLUSTER,
    MIN_HELD_OUT_DECISIONS,
    MIN_JURISDICTIONS_WITH_DEPTH,
    MIN_LABELLED_DECISIONS,
    TARGET_BRIER_SKILL,
)
from auspice.models.hierarchical.model import HierarchicalModel

log = get_logger(__name__, _stage="eval")

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_INSUFFICIENT = "INSUFFICIENT DATA"


@dataclass(slots=True)
class Gate:
    name: str
    passed: bool
    observed: float | None
    condition: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "observed": round(self.observed, 5)
            if self.observed is not None and np.isfinite(self.observed)
            else None,
            "condition": self.condition,
        }


@dataclass(slots=True)
class KillTestResult:
    verdict: str
    cutoff: date
    n_labelled: int
    n_train: int
    n_test: int
    jurisdictions_with_depth: int
    blockers: list[str] = field(default_factory=list)
    gates: list[Gate] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    reliability: dict[str, Any] = field(default_factory=dict)
    residual_notes: list[str] = field(default_factory=list)
    dataset_hash: str | None = None

    @property
    def passed(self) -> bool:
        return self.verdict == VERDICT_PASS

    @property
    def reportable(self) -> bool:
        return self.verdict in (VERDICT_PASS, VERDICT_FAIL)

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "cutoff": self.cutoff.isoformat(),
            "n_labelled": self.n_labelled,
            "n_train": self.n_train,
            "n_test": self.n_test,
            "jurisdictions_with_depth": self.jurisdictions_with_depth,
            "blockers": self.blockers,
            "gates": [g.as_dict() for g in self.gates],
            "metrics": self.metrics,
            "reliability": self.reliability,
            "residual_notes": self.residual_notes,
            "dataset_hash": self.dataset_hash,
        }


def check_sufficiency(dataset: Dataset, *, cutoff: date) -> list[str]:
    """Everything standing between the corpus and a reportable verdict.

    Returns a list of blockers in plain language. An empty list means the test can run.
    """
    blockers: list[str] = []
    decided = dataset.decided
    train, test = dataset.temporal_split(cutoff)

    if decided.height < MIN_LABELLED_DECISIONS:
        blockers.append(
            f"{decided.height} decided applications held, {MIN_LABELLED_DECISIONS} needed. "
            f"Gap of {MIN_LABELLED_DECISIONS - decided.height}."
        )
    if test.height < MIN_HELD_OUT_DECISIONS:
        blockers.append(
            f"{test.height} decisions on or after {cutoff.isoformat()}, "
            f"{MIN_HELD_OUT_DECISIONS} needed to hold out."
        )
    if train.height < MIN_LABELLED_DECISIONS - MIN_HELD_OUT_DECISIONS:
        blockers.append(
            f"{train.height} decisions before {cutoff.isoformat()} to train on, "
            f"{MIN_LABELLED_DECISIONS - MIN_HELD_OUT_DECISIONS} needed."
        )

    depth = dataset.depth_by_jurisdiction()
    with_depth = sum(1 for count in depth.values() if count >= MIN_DEPTH_FOR_CLUSTER)
    if with_depth < MIN_JURISDICTIONS_WITH_DEPTH:
        blockers.append(
            f"{with_depth} jurisdictions hold at least {MIN_DEPTH_FOR_CLUSTER} decisions, "
            f"{MIN_JURISDICTIONS_WITH_DEPTH} needed. Partial pooling has nothing to borrow from "
            "below that."
        )

    if decided.height:
        approval_rate = float(decided.select("approved").mean().item())
        if approval_rate in (0.0, 1.0):
            blockers.append(
                f"every held decision has the same outcome (approval rate {approval_rate:.0%}). "
                "There is nothing to discriminate."
            )

    return blockers


def _fit_calibrator(
    train: pl.DataFrame,
    fit_and_predict: Callable[[pl.DataFrame, pl.DataFrame], np.ndarray],
    *,
    holdout_share: float = 0.25,
) -> PlattCalibrator | IsotonicCalibrator | None:
    """Fit a post hoc calibrator without touching the test set.

    Section 6.9 validation rule 4 applies calibration after fitting. The question is what data to fit
    the calibrator on, and both obvious answers are wrong. Fitting it on the training predictions
    calibrates against predictions the model has already seen, which understates the error. Fitting it
    on the test set is leakage and makes the reported calibration meaningless.

    So the training set is split by date, the model is refitted on the earlier part, and the calibrator
    is fitted on its predictions for the later part. That costs one extra model fit and keeps the test
    set untouched, which is the only version of this that can be published.

    Returns None when the holdout is too small to fit two parameters, in which case no calibration is
    applied and the raw numbers are reported as they are.
    """
    if train.height < 80:
        return None

    ordered = train.sort("decided_on")
    split_at = int(ordered.height * (1.0 - holdout_share))
    earlier = ordered.head(split_at)
    later = ordered.tail(ordered.height - split_at)

    if later.height < 20 or earlier.height < 40:
        return None
    if later.select("approved").to_series().n_unique() < 2:
        return None

    try:
        predictions = fit_and_predict(earlier, later)
    except Exception as exc:
        log.warning("calibrator fit failed", error=str(exc))
        return None

    y_holdout = later.select("approved").to_numpy().ravel().astype(np.float64)
    return choose_calibrator(y_holdout, np.asarray(predictions, dtype=np.float64))


def run_kill_test(
    conn: Connection,
    *,
    cutoff: date,
    dataset: Dataset | None = None,
    include_hierarchical: bool = True,
    hierarchical_samples: int = 1500,
    hierarchical_chains: int = 2,
    calibrate: bool = True,
) -> KillTestResult:
    """Train before the cutoff, predict after it, report the real numbers."""
    resolved = dataset if dataset is not None else load_dataset(conn)
    decided = resolved.decided
    depth = resolved.depth_by_jurisdiction()

    train, test = resolved.temporal_split(cutoff)
    result = KillTestResult(
        verdict=VERDICT_INSUFFICIENT,
        cutoff=cutoff,
        n_labelled=decided.height,
        n_train=train.height,
        n_test=test.height,
        jurisdictions_with_depth=sum(1 for c in depth.values() if c >= MIN_DEPTH_FOR_CLUSTER),
        dataset_hash=resolved.hash() if decided.height else None,
    )

    result.blockers = check_sufficiency(resolved, cutoff=cutoff)
    if result.blockers:
        log.warning(
            "kill test refused",
            reason="insufficient data",
            n_labelled=decided.height,
            n_test=test.height,
        )
        return result

    # --- The benchmark every model must beat -------------------------------
    base_rate = BaseRateModel().fit(train)
    p_reference = base_rate.predict(test)
    y_test = test.select("approved").to_numpy().ravel().astype(np.float64)

    candidates: dict[str, dict[str, Any]] = {}
    columns = resolved.feature_columns

    boosted = BoostedModel(feature_columns=columns).fit(train)
    boosted_calibrator = (
        _fit_calibrator(
            train,
            lambda earlier, later: (
                BoostedModel(feature_columns=columns).fit(earlier).predict(later)
            ),
        )
        if calibrate
        else None
    )
    candidates["gradient_boosted"] = {
        "p": boosted.predict(test),
        "intervals": boosted.predict_interval(test),
        "interval_kind": "bootstrap",
        "calibrator": boosted_calibrator,
        "params": {"importances": boosted.importances(), **boosted.params},
    }

    if include_hierarchical:
        hierarchical = HierarchicalModel(feature_columns=columns)
        hierarchical.fit(
            train,
            samples=hierarchical_samples,
            warmup=hierarchical_samples // 2,
            chains=hierarchical_chains,
        )
        if hierarchical.converged:

            def _refit(earlier: pl.DataFrame, later: pl.DataFrame) -> np.ndarray:
                inner = HierarchicalModel(feature_columns=columns)
                inner.fit(
                    earlier,
                    samples=max(600, hierarchical_samples // 2),
                    warmup=max(300, hierarchical_samples // 4),
                    chains=1,
                )
                return inner.predict(later)

            candidates["hierarchical"] = {
                "p": hierarchical.predict(test),
                "intervals": hierarchical.predict_interval(test),
                "interval_kind": "credible",
                "calibrator": _fit_calibrator(train, _refit) if calibrate else None,
                "params": hierarchical.params(),
            }
        else:
            result.residual_notes.append(
                "the hierarchical model did not converge (r-hat "
                f"{hierarchical.diagnostics.get('max_r_hat')}, "
                f"{hierarchical.diagnostics.get('divergences')} divergent transitions), so it is "
                "excluded. An interval from an untrustworthy posterior is worse than no interval."
            )

    # --- Score every candidate --------------------------------------------
    scored: dict[str, dict[str, Any]] = {}
    for name, candidate in candidates.items():
        raw = np.asarray(candidate["p"], dtype=np.float64)
        calibrator = candidate.get("calibrator")
        p = np.asarray(calibrator.transform(raw), dtype=np.float64) if calibrator else raw

        intervals = np.asarray(candidate["intervals"], dtype=np.float64)
        if calibrator is not None:
            # Apply the same monotone map to the interval bounds. A monotone transform of a quantile
            # is the quantile of the transform, so this is exact rather than an approximation.
            intervals = np.stack(
                [calibrator.transform(intervals[:, 0]), calibrator.transform(intervals[:, 1])],
                axis=1,
            )
            intervals = np.sort(intervals, axis=1)
            # Keep the point estimate inside its own interval after recalibration.
            intervals[:, 0] = np.minimum(intervals[:, 0], p)
            intervals[:, 1] = np.maximum(intervals[:, 1], p)

        curve = reliability_curve(y_test, p)
        raw_curve = reliability_curve(y_test, raw)
        abstained = _abstention_mask(test, intervals)

        scored[name] = {
            "brier": brier_score(y_test, p),
            "brier_skill_vs_base_rate": brier_skill_score(y_test, p, p_reference),
            "log_loss": log_loss(y_test, p),
            "auc": auc(y_test, p),
            "expected_calibration_error": curve.expected_calibration_error,
            "expected_calibration_error_uncalibrated": raw_curve.expected_calibration_error,
            "maximum_calibration_error": curve.maximum_calibration_error,
            "bins_within_ten_points": curve.worst_bin_within_ten_points,
            "coverage_80": binned_interval_coverage(y_test, intervals),
            "interval_kind": candidate["interval_kind"],
            "mean_interval_width": float(np.mean(intervals[:, 1] - intervals[:, 0])),
            "calibrator": calibrator.params() if calibrator else None,
            "abstention": abstention_precision(y_test, p, abstained),
            "params": candidate["params"],
            "p": p,
            "_curve": curve,
        }

    # The reported model is the best by Brier skill. Chosen before the gates are applied, so a model
    # is never selected because it happens to clear a threshold.
    primary_name = max(
        scored,
        key=lambda n: (
            scored[n]["brier_skill_vs_base_rate"]
            if np.isfinite(scored[n]["brier_skill_vs_base_rate"])
            else -np.inf
        ),
    )
    primary = scored[primary_name]
    primary_curve: ReliabilityCurve = primary.pop("_curve")
    for other in scored.values():
        other.pop("_curve", None)

    result.metrics = {
        "primary_model": primary_name,
        "base_rate_brier": brier_score(y_test, p_reference),
        "base_rate_params": base_rate.params(),
        "models": {name: _display(values) for name, values in scored.items()},
    }
    result.reliability = primary_curve.as_dict()

    # --- The gates ---------------------------------------------------------
    skill = primary["brier_skill_vs_base_rate"]
    ece = primary["expected_calibration_error"]
    coverage = primary["coverage_80"]
    model_auc = primary["auc"]
    abstention = primary["abstention"]

    result.gates = [
        Gate(
            "brier skill against the base rate",
            bool(np.isfinite(skill) and skill >= MIN_BRIER_SKILL),
            skill,
            f"at least {MIN_BRIER_SKILL:.2f} (target {TARGET_BRIER_SKILL:.2f})",
        ),
        Gate(
            "expected calibration error",
            bool(np.isfinite(ece) and ece < MAX_ECE),
            ece,
            f"below {MAX_ECE:.2f}",
        ),
        Gate(
            "80 percent interval coverage",
            bool(np.isfinite(coverage) and COVERAGE_BAND[0] <= coverage <= COVERAGE_BAND[1]),
            coverage,
            f"between {COVERAGE_BAND[0]:.2f} and {COVERAGE_BAND[1]:.2f}",
        ),
        Gate(
            "area under the ROC curve",
            bool(np.isfinite(model_auc) and model_auc > MIN_AUC),
            model_auc,
            f"above {MIN_AUC:.2f}",
        ),
        Gate(
            "abstention is better than lazy",
            _abstention_gate(abstention),
            abstention.get("improvement"),
            "answered rows materially better than abstained rows, or nothing abstained",
        ),
    ]

    result.verdict = VERDICT_PASS if all(g.passed for g in result.gates) else VERDICT_FAIL
    result.residual_notes.extend(
        _residual_notes(test, primary.get("p", None), y_test, scored, primary_name)
    )

    log.info(
        "kill test complete",
        verdict=result.verdict,
        primary=primary_name,
        brier_skill=round(skill, 4) if np.isfinite(skill) else None,
        ece=round(ece, 4) if np.isfinite(ece) else None,
        coverage=round(coverage, 4) if np.isfinite(coverage) else None,
    )
    return result


def _abstention_mask(test: pl.DataFrame, intervals: np.ndarray) -> np.ndarray:
    """The section 8.4 rule, applied to the held out rows.

        abstain if n_comparable_decisions < 3
                AND cluster_pooling_weight > 0.8
                AND credible_interval_width > 0.35

    All three conditions, as written. A rule that fires on any one of them would abstain on most of
    the corpus, which is not intelligence, it is refusing to work.
    """
    width = intervals[:, 1] - intervals[:, 0]

    if "n_comparable_decisions" in test.columns:
        comparables = test.select("n_comparable_decisions").to_numpy().ravel()
        comparables = np.where(np.isfinite(comparables), comparables, 0.0)
    else:
        comparables = np.zeros(test.height, dtype=np.float64)

    # Pooling weight is derived from the same evidence count the base rate model uses, so the two
    # agree about how thin a jurisdiction is.
    pooling = 4.0 / (4.0 + comparables)

    mask: np.ndarray = (
        (comparables < ABSTAIN_MAX_COMPARABLES)
        & (pooling > ABSTAIN_MAX_POOLING_WEIGHT)
        & (width > ABSTAIN_MAX_INTERVAL_WIDTH)
    )
    return mask


def _abstention_gate(abstention: dict[str, float | None]) -> bool:
    n_abstained = abstention.get("n_abstained") or 0
    if not n_abstained:
        # Nothing was abstained on, so the rule made no claim and cannot have made a bad one.
        return True
    improvement = abstention.get("improvement")
    if improvement is None:
        return False
    return float(improvement) >= (1.0 - MIN_ABSTENTION_PRECISION)


def _display(values: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in values.items():
        if key == "p":
            continue
        if isinstance(value, float):
            out[key] = round(value, 5) if np.isfinite(value) else None
        else:
            out[key] = value
    return out


def _residual_notes(
    test: pl.DataFrame,
    _p: Any,
    y_test: np.ndarray,
    scored: dict[str, dict[str, Any]],
    primary_name: str,
) -> list[str]:
    """An honest note about what the residuals look like.

    Section 12 day 15 to 16 requires this on a failure: write an honest note about what you saw in the
    residuals and stop. It is produced on a pass too, because the residual structure is where the next
    feature comes from.
    """
    notes: list[str] = []
    p = np.asarray(scored[primary_name]["p"], dtype=np.float64)
    residual = y_test - p

    if len(residual) < 10:
        return notes

    worst_jurisdiction: tuple[str, float] | None = None
    for slug in sorted(set(test.select("jurisdiction").to_series().to_list())):
        mask = np.asarray(
            [str(v) == slug for v in test.select("jurisdiction").to_series()], dtype=bool
        )
        if int(mask.sum()) < 3:
            continue
        bias = float(np.mean(residual[mask]))
        if worst_jurisdiction is None or abs(bias) > abs(worst_jurisdiction[1]):
            worst_jurisdiction = (slug, bias)

    if worst_jurisdiction is not None and abs(worst_jurisdiction[1]) > 0.15:
        slug, bias = worst_jurisdiction
        direction = "under" if bias > 0 else "over"
        notes.append(
            f"the largest jurisdiction level bias is {slug}, where the model {direction} predicts "
            f"approval by {abs(bias):.2f} on average. That is the first place to look for a missing "
            "feature rather than a modelling problem."
        )

    high = p >= 0.7
    low = p <= 0.3
    if int(high.sum()) >= 5:
        observed = float(np.mean(y_test[high]))
        if abs(observed - float(np.mean(p[high]))) > 0.12:
            notes.append(
                f"in the high confidence band the model predicts {float(np.mean(p[high])):.2f} and "
                f"observes {observed:.2f}. Overconfidence at the top of the range is the failure mode "
                "that costs a customer money, because that is the band they act on."
            )
    if int(low.sum()) >= 5:
        observed = float(np.mean(y_test[low]))
        if abs(observed - float(np.mean(p[low]))) > 0.12:
            notes.append(
                f"in the low confidence band the model predicts {float(np.mean(p[low])):.2f} and "
                f"observes {observed:.2f}."
            )

    if "hierarchical" in scored and "gradient_boosted" in scored:
        h = scored["hierarchical"]["brier_skill_vs_base_rate"]
        g = scored["gradient_boosted"]["brier_skill_vs_base_rate"]
        if np.isfinite(h) and np.isfinite(g) and g > h:
            notes.append(
                f"the boosted model beats the hierarchical model on skill ({g:.3f} against {h:.3f}). "
                "Section 6.8 says ship the simpler one when that happens, and it means the pooling "
                "structure is not yet earning its complexity."
            )

    return notes
