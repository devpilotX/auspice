"""Calibration and evaluation metrics.

Section 6.9: calibration is not a metric here, it is the product. So these are written out rather
than imported from scikit-learn wherever the definition matters, because the exact definition is what
gets published and a library changing a default binning strategy must not silently change a published
number.

Everything here is tested against closed form answers in ``tests/unit/test_metrics.py``. A calibration
function with a sign error is the single most dangerous bug in this codebase: it would produce a
confident, wrong accuracy record, which is worse than having no record at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

import numpy as np

DEFAULT_BINS = 10


# ---------------------------------------------------------------------------
# Scoring rules
# ---------------------------------------------------------------------------
def brier_score(y: np.ndarray, p: np.ndarray) -> float:
    """Mean squared error of probabilistic forecasts. Lower is better.

    The headline number in section 6.9: single, honest, hard to game.
    """
    y = np.asarray(y, dtype=np.float64)
    p = np.asarray(p, dtype=np.float64)
    if y.size == 0:
        return float("nan")
    return float(np.mean((p - y) ** 2))


def brier_skill_score(y: np.ndarray, p: np.ndarray, p_reference: np.ndarray) -> float:
    """Fractional improvement in Brier score over a reference forecast.

    Zero means no better than the reference. One means perfect. Negative means worse than the
    reference, which is the result that stops the company.
    """
    model = brier_score(y, p)
    reference = brier_score(y, p_reference)
    if not np.isfinite(reference) or reference <= 0:
        return float("nan")
    return float(1.0 - model / reference)


def log_loss(y: np.ndarray, p: np.ndarray, *, epsilon: float = 1e-12) -> float:
    y = np.asarray(y, dtype=np.float64)
    p = np.clip(np.asarray(p, dtype=np.float64), epsilon, 1.0 - epsilon)
    if y.size == 0:
        return float("nan")
    return float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))


def auc(y: np.ndarray, p: np.ndarray) -> float:
    """Area under the ROC curve, by the rank formulation, with ties handled correctly.

    Written out rather than imported because the tie handling is exactly where a hand rolled AUC
    usually goes wrong, and portfolio screening depends only on correct ordering, so this number
    carries real weight.
    """
    y = np.asarray(y, dtype=np.float64)
    p = np.asarray(p, dtype=np.float64)
    positives = int(np.sum(y == 1))
    negatives = int(np.sum(y == 0))
    if positives == 0 or negatives == 0:
        return float("nan")

    order = np.argsort(p, kind="mergesort")
    sorted_p = p[order]
    ranks = np.empty(len(p), dtype=np.float64)

    index = 0
    while index < len(sorted_p):
        end = index
        while end + 1 < len(sorted_p) and sorted_p[end + 1] == sorted_p[index]:
            end += 1
        # Average rank for the tied block. Ranks are one based.
        average = (index + end) / 2.0 + 1.0
        ranks[order[index : end + 1]] = average
        index = end + 1

    rank_sum_positive = float(np.sum(ranks[y == 1]))
    return float((rank_sum_positive - positives * (positives + 1) / 2.0) / (positives * negatives))


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ReliabilityBin:
    lower: float
    upper: float
    count: int
    mean_predicted: float
    observed_frequency: float

    @property
    def gap(self) -> float:
        return self.observed_frequency - self.mean_predicted

    def wilson_interval(self, *, z: float = 1.96) -> tuple[float, float]:
        """Wilson score interval on the observed frequency.

        The reliability curve is the chart a customer actually checks, and a bin holding three
        observations must not look as authoritative as a bin holding three hundred. A normal
        approximation would give a symmetric interval that runs past zero and one on the end bins,
        which is visibly wrong on exactly the bins that matter most.
        """
        n = self.count
        if n == 0:
            return (0.0, 1.0)
        phat = self.observed_frequency
        denominator = 1.0 + z**2 / n
        centre = (phat + z**2 / (2 * n)) / denominator
        margin = z * np.sqrt(phat * (1.0 - phat) / n + z**2 / (4 * n**2)) / denominator
        return (float(max(0.0, centre - margin)), float(min(1.0, centre + margin)))


@dataclass(slots=True)
class ReliabilityCurve:
    bins: list[ReliabilityBin] = field(default_factory=list)
    n: int = 0

    @property
    def expected_calibration_error(self) -> float:
        """Count weighted mean absolute gap. Section 6.9 target is below 0.08."""
        if not self.n:
            return float("nan")
        return float(sum(b.count * abs(b.gap) for b in self.bins) / self.n)

    @property
    def maximum_calibration_error(self) -> float:
        populated = [b for b in self.bins if b.count > 0]
        if not populated:
            return float("nan")
        return float(max(abs(b.gap) for b in populated))

    @property
    def worst_bin_within_ten_points(self) -> bool:
        """Section 6.9: within plus or minus 10 points per bin.

        Bins with fewer than five observations are excluded from the test, because a single
        observation in a bin gives a gap of up to one and failing on that is noise, not miscalibration.
        """
        material = [b for b in self.bins if b.count >= 5]
        if not material:
            return False
        return all(abs(b.gap) <= 0.10 for b in material)

    def as_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "expected_calibration_error": round(self.expected_calibration_error, 5)
            if np.isfinite(self.expected_calibration_error)
            else None,
            "maximum_calibration_error": round(self.maximum_calibration_error, 5)
            if np.isfinite(self.maximum_calibration_error)
            else None,
            "bins": [
                {
                    "lower": round(b.lower, 3),
                    "upper": round(b.upper, 3),
                    "count": b.count,
                    "mean_predicted": round(b.mean_predicted, 5),
                    "observed_frequency": round(b.observed_frequency, 5),
                    "interval": [round(v, 5) for v in b.wilson_interval()],
                }
                for b in self.bins
            ],
        }


def reliability_curve(
    y: np.ndarray, p: np.ndarray, *, bins: int = DEFAULT_BINS
) -> ReliabilityCurve:
    """Predicted against observed frequency in equal width bins.

    Equal width rather than equal count, deliberately. Equal count bins make a curve look smoother and
    hide the region where the model is overconfident, and the whole purpose of publishing the curve is
    to show that region.
    """
    y = np.asarray(y, dtype=np.float64)
    p = np.asarray(p, dtype=np.float64)
    curve = ReliabilityCurve(n=int(y.size))
    if y.size == 0:
        return curve

    edges = np.linspace(0.0, 1.0, bins + 1)
    for index in range(bins):
        lower, upper = edges[index], edges[index + 1]
        mask = (p >= lower) & (p <= upper) if index == bins - 1 else (p >= lower) & (p < upper)
        count = int(np.sum(mask))
        curve.bins.append(
            ReliabilityBin(
                lower=float(lower),
                upper=float(upper),
                count=count,
                mean_predicted=float(np.mean(p[mask])) if count else float((lower + upper) / 2),
                observed_frequency=float(np.mean(y[mask])) if count else 0.0,
            )
        )
    return curve


def interval_coverage(y: np.ndarray, intervals: np.ndarray) -> float:
    """Share of outcomes whose observed frequency is consistent with the stated interval.

    A binary outcome is never "inside" a probability interval in the naive sense, so coverage is
    computed the way it is actually meaningful for a probabilistic forecast: the outcome is counted as
    covered when the interval contains a probability that would not reject the observation at the
    stated level. Concretely, a positive outcome is covered when the interval's upper bound is at
    least the significance floor, and a negative outcome is covered when the lower bound is at most
    the ceiling.

    This is a strict reading and it can fail. The alternative used by most published calibration
    claims, checking whether the point estimate falls inside its own interval, is vacuous.
    """
    y = np.asarray(y, dtype=np.float64)
    intervals = np.asarray(intervals, dtype=np.float64)
    if y.size == 0:
        return float("nan")
    lower = intervals[:, 0]
    upper = intervals[:, 1]
    covered = np.where(y == 1, upper >= 0.5, lower <= 0.5)
    return float(np.mean(covered))


def binned_interval_coverage(
    y: np.ndarray, intervals: np.ndarray, *, min_group: int = 8, max_groups: int = 12
) -> float:
    """Coverage measured the way a statistician would defend it, and a customer would check it.

    Rows are grouped by the midpoint of their interval. Within each group the observed approval
    frequency is computed, and the group counts as covered when that frequency falls inside the mean
    interval for the group. This tests the claim the interval actually makes, which is about
    frequencies rather than about individual binary outcomes.

    Grouping is unavoidable: a single binary outcome is never "inside" a probability interval in any
    meaningful sense. The group count adapts to the sample so that a large held out set is tested more
    sharply than a small one, and groups below ``min_group`` rows are dropped rather than allowed to
    pass on noise.

    Reading the result honestly matters in both directions. Coverage well below 0.80 means the
    intervals are too narrow, which is overconfidence. Coverage at 1.00 means they are too wide, which
    is a different failure and still a failure: an interval that always contains the answer carries no
    information. The gate in ``thresholds.py`` is a band for exactly this reason.
    """
    y = np.asarray(y, dtype=np.float64)
    intervals = np.asarray(intervals, dtype=np.float64)
    if y.size == 0:
        return float("nan")

    n_groups = int(np.clip(y.size // min_group, 1, max_groups))
    if n_groups < 2:
        return float("nan")

    midpoints = intervals.mean(axis=1)
    order = np.argsort(midpoints, kind="mergesort")
    groups = np.array_split(order, n_groups)

    covered = 0
    total = 0
    for group in groups:
        if group.size < min_group:
            continue
        observed = float(np.mean(y[group]))
        low = float(np.mean(intervals[group, 0]))
        high = float(np.mean(intervals[group, 1]))
        total += 1
        if low <= observed <= high:
            covered += 1

    if total == 0:
        return float("nan")
    return float(covered / total)


def interval_coverage_against_truth(true_probability: np.ndarray, intervals: np.ndarray) -> float:
    """Share of intervals containing the true probability.

    This is what an 80 percent credible interval actually claims, and it is the only exact test of it.
    It requires knowing the true probability, so it can only be run on a synthetic corpus, and it is
    used in ``tests/unit/test_hierarchical_recovers_truth.py`` to prove the interval construction is
    correct before that construction is trusted on real data.
    """
    true_probability = np.asarray(true_probability, dtype=np.float64)
    intervals = np.asarray(intervals, dtype=np.float64)
    if true_probability.size == 0:
        return float("nan")
    inside = (intervals[:, 0] <= true_probability) & (true_probability <= intervals[:, 1])
    return float(np.mean(inside))


# ---------------------------------------------------------------------------
# Post hoc calibration
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class PlattCalibrator:
    """Logistic recalibration. Section 6.9 validation rule 4, for small samples.

    Two parameters, fitted on held out predictions. On a few hundred rows isotonic regression has
    enough freedom to fit the noise in the validation set and then fail out of sample, which is the
    opposite of what a calibrator is for.
    """

    slope: float = 1.0
    intercept: float = 0.0
    n_fit: int = 0

    def fit(self, y: np.ndarray, p: np.ndarray) -> PlattCalibrator:
        y = np.asarray(y, dtype=np.float64)
        logits = _logit(np.asarray(p, dtype=np.float64))
        self.n_fit = int(y.size)

        if y.size < 20 or len(np.unique(y)) < 2:
            # Not enough to fit two parameters without overfitting them. Identity is honest.
            self.slope, self.intercept = 1.0, 0.0
            return self

        weights = np.array([1.0, 0.0])
        design = np.column_stack([logits, np.ones_like(logits)])
        for _ in range(100):
            eta = design @ weights
            mu = 1.0 / (1.0 + np.exp(-np.clip(eta, -30, 30)))
            variance = np.clip(mu * (1 - mu), 1e-9, None)
            gradient = design.T @ (y - mu)
            hessian = -(design.T * variance) @ design
            try:
                step = np.linalg.solve(hessian, -gradient)
            except np.linalg.LinAlgError:
                break
            weights = weights + np.clip(step, -2.0, 2.0)
            if np.max(np.abs(step)) < 1e-9:
                break

        self.slope, self.intercept = float(weights[0]), float(weights[1])
        return self

    def transform(self, p: np.ndarray) -> np.ndarray:
        logits = _logit(np.asarray(p, dtype=np.float64))
        return np.asarray(
            1.0 / (1.0 + np.exp(-np.clip(self.slope * logits + self.intercept, -30, 30))),
            dtype=np.float64,
        )

    def params(self) -> dict[str, Any]:
        return {
            "kind": "platt",
            "slope": round(self.slope, 6),
            "intercept": round(self.intercept, 6),
            "n_fit": self.n_fit,
        }


@dataclass(slots=True)
class IsotonicCalibrator:
    """Isotonic recalibration, for when there is enough held out data to support it."""

    thresholds: np.ndarray | None = None
    values: np.ndarray | None = None
    n_fit: int = 0

    def fit(self, y: np.ndarray, p: np.ndarray) -> IsotonicCalibrator:
        from sklearn.isotonic import IsotonicRegression

        y = np.asarray(y, dtype=np.float64)
        p = np.asarray(p, dtype=np.float64)
        self.n_fit = int(y.size)
        if y.size < 100 or len(np.unique(y)) < 2:
            self.thresholds, self.values = None, None
            return self
        fitted = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(p, y)
        self.thresholds = np.asarray(fitted.X_thresholds_, dtype=np.float64)
        self.values = np.asarray(fitted.y_thresholds_, dtype=np.float64)
        return self

    def transform(self, p: np.ndarray) -> np.ndarray:
        values = np.asarray(p, dtype=np.float64)
        if self.thresholds is None or self.values is None:
            return values
        # np.interp is annotated as returning Any when its inputs are, so the result is cast rather
        # than merely annotated. cast states that the narrowing is the author's claim, which is what it
        # is: numpy guarantees an ndarray here, its stubs do not say so.
        interpolated = np.interp(values, self.thresholds, self.values)
        return cast("np.ndarray", np.asarray(interpolated, dtype=np.float64))

    def params(self) -> dict[str, Any]:
        return {
            "kind": "isotonic",
            "n_fit": self.n_fit,
            "knots": len(self.thresholds) if self.thresholds is not None else 0,
        }


def choose_calibrator(y: np.ndarray, p: np.ndarray) -> PlattCalibrator | IsotonicCalibrator:
    """Isotonic above 100 held out rows, Platt below. Section 6.9 rule 4."""
    if np.asarray(y).size >= 100:
        return IsotonicCalibrator().fit(y, p)
    return PlattCalibrator().fit(y, p)


def _logit(p: np.ndarray, *, epsilon: float = 1e-9) -> np.ndarray:
    clipped = np.clip(p, epsilon, 1.0 - epsilon)
    return cast("np.ndarray", np.log(clipped / (1.0 - clipped)))


# ---------------------------------------------------------------------------
# Abstention
# ---------------------------------------------------------------------------
def abstention_precision(
    y: np.ndarray, p: np.ndarray, abstained: np.ndarray
) -> dict[str, float | None]:
    """Is abstention intelligent or lazy? Section 6.9 and section 8.4.

    Reports the Brier score on answered rows and on abstained rows separately. If the model is worse
    on the rows it chose to answer, abstention is selecting the wrong cases and is doing harm.
    """
    y = np.asarray(y, dtype=np.float64)
    p = np.asarray(p, dtype=np.float64)
    abstained = np.asarray(abstained, dtype=bool)

    answered = ~abstained
    result: dict[str, float | None] = {
        "n_answered": int(np.sum(answered)),
        "n_abstained": int(np.sum(abstained)),
        "abstention_rate": float(np.mean(abstained)) if y.size else None,
        "brier_answered": brier_score(y[answered], p[answered]) if np.any(answered) else None,
        "brier_abstained": brier_score(y[abstained], p[abstained]) if np.any(abstained) else None,
    }

    answered_brier = result["brier_answered"]
    abstained_brier = result["brier_abstained"]
    if answered_brier is not None and abstained_brier is not None and abstained_brier > 0:
        result["improvement"] = round(1.0 - answered_brier / abstained_brier, 4)
    else:
        result["improvement"] = None
    return result
