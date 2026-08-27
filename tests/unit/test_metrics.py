"""The calibration mathematics.

Section 6.9 makes calibration the product rather than a metric, which makes a sign error in this
module the single most dangerous bug in the codebase: it would produce a confident, wrong, published
accuracy record. So every function is checked against a closed form answer rather than against
another implementation.
"""

from __future__ import annotations

import numpy as np
import pytest

from auspice.models.eval.metrics import (
    IsotonicCalibrator,
    PlattCalibrator,
    abstention_precision,
    auc,
    binned_interval_coverage,
    brier_score,
    brier_skill_score,
    interval_coverage_against_truth,
    log_loss,
    reliability_curve,
)


class TestBrier:
    def test_perfect_forecast_scores_zero(self) -> None:
        y = np.array([1, 0, 1, 0])
        assert brier_score(y, np.array([1.0, 0.0, 1.0, 0.0])) == 0.0

    def test_worst_forecast_scores_one(self) -> None:
        y = np.array([1, 0])
        assert brier_score(y, np.array([0.0, 1.0])) == 1.0

    def test_always_half_scores_a_quarter(self) -> None:
        y = np.array([1, 0, 1, 1, 0])
        assert brier_score(y, np.full(5, 0.5)) == pytest.approx(0.25)

    def test_closed_form(self) -> None:
        # ((0.8-1)^2 + (0.3-0)^2 + (0.6-1)^2) / 3
        y = np.array([1, 0, 1])
        p = np.array([0.8, 0.3, 0.6])
        expected = (0.04 + 0.09 + 0.16) / 3
        assert brier_score(y, p) == pytest.approx(expected)

    def test_skill_is_zero_against_itself(self) -> None:
        y = np.array([1, 0, 1, 0, 1])
        p = np.array([0.7, 0.2, 0.6, 0.4, 0.9])
        assert brier_skill_score(y, p, p) == pytest.approx(0.0)

    def test_skill_is_negative_when_worse_than_reference(self) -> None:
        y = np.array([1, 1, 0, 0])
        good = np.array([0.9, 0.8, 0.2, 0.1])
        bad = np.array([0.4, 0.4, 0.6, 0.6])
        assert brier_skill_score(y, bad, good) < 0

    def test_skill_is_one_for_a_perfect_model(self) -> None:
        y = np.array([1, 0, 1, 0])
        perfect = y.astype(float)
        reference = np.full(4, 0.5)
        assert brier_skill_score(y, perfect, reference) == pytest.approx(1.0)


class TestLogLoss:
    def test_closed_form(self) -> None:
        y = np.array([1, 0])
        p = np.array([0.5, 0.5])
        assert log_loss(y, p) == pytest.approx(float(np.log(2)))

    def test_clipping_prevents_infinity(self) -> None:
        assert np.isfinite(log_loss(np.array([1]), np.array([0.0])))


class TestAuc:
    def test_perfect_separation(self) -> None:
        y = np.array([0, 0, 1, 1])
        assert auc(y, np.array([0.1, 0.2, 0.8, 0.9])) == pytest.approx(1.0)

    def test_inverted_separation(self) -> None:
        y = np.array([0, 0, 1, 1])
        assert auc(y, np.array([0.9, 0.8, 0.2, 0.1])) == pytest.approx(0.0)

    def test_all_ties_is_one_half(self) -> None:
        """The case a hand rolled AUC usually gets wrong."""
        y = np.array([0, 1, 0, 1])
        assert auc(y, np.full(4, 0.5)) == pytest.approx(0.5)

    def test_partial_ties(self) -> None:
        # Two positives at 0.6, two negatives at 0.6 and 0.2. Pairs: (0.6,0.6) tie counts 0.5 twice,
        # (0.6,0.2) wins twice. So (0.5 + 0.5 + 1 + 1) / 4 = 0.75.
        y = np.array([1, 1, 0, 0])
        p = np.array([0.6, 0.6, 0.6, 0.2])
        assert auc(y, p) == pytest.approx(0.75)

    def test_single_class_is_undefined(self) -> None:
        assert np.isnan(auc(np.array([1, 1, 1]), np.array([0.2, 0.5, 0.9])))


class TestReliability:
    def test_perfectly_calibrated_has_no_error(self) -> None:
        """Ten bins, each with the observed frequency equal to the predicted probability."""
        y_parts: list[np.ndarray] = []
        p_parts: list[np.ndarray] = []
        for index in range(10):
            probability = index / 10 + 0.05
            n = 200
            positives = round(probability * n)
            y_parts.append(np.concatenate([np.ones(positives), np.zeros(n - positives)]))
            p_parts.append(np.full(n, probability))
        y = np.concatenate(y_parts)
        p = np.concatenate(p_parts)

        curve = reliability_curve(y, p)
        assert curve.expected_calibration_error < 0.005
        assert curve.worst_bin_within_ten_points

    def test_systematic_overconfidence_is_detected(self) -> None:
        """Predicts 0.9 everywhere, observes 0.5. ECE should be about 0.4."""
        y = np.array([1, 0] * 100)
        p = np.full(200, 0.9)
        curve = reliability_curve(y, p)
        assert curve.expected_calibration_error == pytest.approx(0.4, abs=0.01)
        assert not curve.worst_bin_within_ten_points

    def test_bins_partition_the_unit_interval(self) -> None:
        y = np.array([1, 0, 1])
        p = np.array([0.0, 0.5, 1.0])
        curve = reliability_curve(y, p)
        assert sum(b.count for b in curve.bins) == 3, "every row must land in exactly one bin"

    def test_wilson_interval_is_asymmetric_at_the_edges(self) -> None:
        """A normal approximation would run past one here, which is visibly wrong on the page."""
        curve = reliability_curve(np.ones(10), np.full(10, 0.95))
        populated = next(b for b in curve.bins if b.count > 0)
        low, high = populated.wilson_interval()
        assert 0.0 <= low <= 1.0
        assert high <= 1.0
        assert low < 1.0, "an interval on ten out of ten must not be a point"

    def test_empty_input_is_not_an_error(self) -> None:
        curve = reliability_curve(np.array([]), np.array([]))
        assert curve.n == 0
        assert np.isnan(curve.expected_calibration_error)


class TestCoverage:
    def test_truth_based_coverage_is_exact(self) -> None:
        true_p = np.array([0.5, 0.5, 0.5, 0.5])
        intervals = np.array([[0.4, 0.6], [0.4, 0.6], [0.9, 1.0], [0.0, 0.1]])
        assert interval_coverage_against_truth(true_p, intervals) == pytest.approx(0.5)

    def test_binned_coverage_needs_enough_rows(self) -> None:
        assert np.isnan(binned_interval_coverage(np.array([1, 0]), np.array([[0.2, 0.8]] * 2)))

    def test_binned_coverage_detects_intervals_that_are_far_too_narrow(self) -> None:
        rng = np.random.default_rng(7)
        y = (rng.random(200) < 0.5).astype(float)
        # Claims 0.9 to 0.91 everywhere while the truth is 0.5.
        intervals = np.tile(np.array([0.90, 0.91]), (200, 1))
        assert binned_interval_coverage(y, intervals) == pytest.approx(0.0)

    def test_binned_coverage_is_high_for_intervals_that_are_far_too_wide(self) -> None:
        """Reads as 1.0, which the threshold band correctly fails. Too wide is also dishonest."""
        rng = np.random.default_rng(7)
        y = (rng.random(200) < 0.5).astype(float)
        intervals = np.tile(np.array([0.0, 1.0]), (200, 1))
        assert binned_interval_coverage(y, intervals) == pytest.approx(1.0)


class TestCalibrators:
    def test_platt_corrects_a_known_logit_shift(self) -> None:
        rng = np.random.default_rng(11)
        n = 4000
        true_p = rng.uniform(0.05, 0.95, n)
        y = (rng.random(n) < true_p).astype(float)
        # Push the predictions toward the extremes by inflating the logit.
        logits = np.log(true_p / (1 - true_p))
        miscalibrated = 1 / (1 + np.exp(-1.8 * logits))

        before = reliability_curve(y, miscalibrated).expected_calibration_error
        calibrator = PlattCalibrator().fit(y, miscalibrated)
        after = reliability_curve(y, calibrator.transform(miscalibrated)).expected_calibration_error

        assert after < before
        assert after < 0.03
        # Recovers roughly the inverse of the 1.8 inflation.
        assert calibrator.slope == pytest.approx(1 / 1.8, rel=0.35)

    def test_platt_declines_on_a_tiny_sample(self) -> None:
        """Fitting two parameters on twelve rows overfits them, so identity is the honest answer."""
        calibrator = PlattCalibrator().fit(np.array([1, 0] * 6), np.full(12, 0.7))
        assert calibrator.slope == 1.0
        assert calibrator.intercept == 0.0

    def test_isotonic_declines_below_a_hundred_rows(self) -> None:
        calibrator = IsotonicCalibrator().fit(np.array([1, 0] * 20), np.linspace(0.1, 0.9, 40))
        assert calibrator.thresholds is None
        # Declining means passing values through unchanged, not returning zeros.
        p = np.array([0.3, 0.7])
        assert np.allclose(calibrator.transform(p), p)

    def test_isotonic_is_monotone(self) -> None:
        rng = np.random.default_rng(3)
        n = 600
        p = rng.uniform(0, 1, n)
        y = (rng.random(n) < p**1.5).astype(float)
        calibrator = IsotonicCalibrator().fit(y, p)
        grid = np.linspace(0, 1, 50)
        transformed = calibrator.transform(grid)
        assert np.all(np.diff(transformed) >= -1e-9)


class TestAbstentionPrecision:
    def test_reports_both_arms(self) -> None:
        y = np.array([1, 1, 0, 0])
        p = np.array([0.9, 0.8, 0.5, 0.5])
        abstained = np.array([False, False, True, True])
        result = abstention_precision(y, p, abstained)
        assert result["n_answered"] == 2
        assert result["n_abstained"] == 2
        assert result["brier_answered"] is not None
        assert result["brier_abstained"] is not None
        assert result["brier_answered"] < result["brier_abstained"]
        assert result["improvement"] is not None
        assert result["improvement"] > 0

    def test_lazy_abstention_shows_no_improvement(self) -> None:
        """Abstaining on the easy rows should be visible as a negative improvement."""
        y = np.array([1, 1, 0, 0])
        p = np.array([0.5, 0.5, 0.02, 0.02])
        abstained = np.array([False, False, True, True])
        result = abstention_precision(y, p, abstained)
        assert result["improvement"] is not None
        assert result["improvement"] < 0

    def test_no_abstentions_is_handled(self) -> None:
        result = abstention_precision(
            np.array([1, 0]), np.array([0.6, 0.4]), np.array([False, False])
        )
        assert result["n_abstained"] == 0
        assert result["brier_abstained"] is None
        assert result["improvement"] is None
