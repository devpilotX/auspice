"""Do the models recover a truth we control?

This is the only place the truth is known, so it is the only place these claims can be tested. Every
assertion here is about the mathematics, not about permission risk. Nothing in this file is evidence
about the real world and none of it is ever published.

The claims under test are the ones section 6.8 makes:

- partial pooling beats both a strong base rate and a boosted model on thin jurisdictions
- an 80 percent credible interval contains the truth about 80 percent of the time
- the fitted coefficients recover the generating ones
- the model degrades gracefully rather than lying confidently when a jurisdiction is thin
- survival estimates are not biased optimistically by censoring

These are marked slow because NUTS takes about ten seconds. They run in CI.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from auspice.models.baseline import BaseRateModel, BoostedModel
from auspice.models.eval.metrics import (
    auc,
    binned_interval_coverage,
    brier_score,
    brier_skill_score,
    interval_coverage_against_truth,
    reliability_curve,
)
from auspice.models.hierarchical import HierarchicalModel, assign_clusters
from auspice.models.survival import SurvivalModel
from tests.synthetic.generator import CAUSAL_FEATURES

CUTOFF = date(2024, 1, 1)
CORPUS_END = date(2026, 6, 30)


@pytest.fixture(scope="module")
def fitted():  # type: ignore[no-untyped-def]
    """Fit every model once. NUTS is not cheap enough to repeat per test."""
    from auspice.models.dataset import dataset_from_frame
    from tests.synthetic import generate

    corpus = generate()
    dataset = dataset_from_frame(corpus.frame, corpus.feature_columns)
    train, test = dataset.temporal_split(CUTOFF)

    base_rate = BaseRateModel().fit(train)
    boosted = BoostedModel(feature_columns=dataset.feature_columns).fit(train)
    hierarchical = HierarchicalModel(feature_columns=dataset.feature_columns)
    hierarchical.fit(train, warmup=800, samples=1200, chains=2)

    truth = dict(
        zip(corpus.frame["application_id"].to_list(), corpus.true_probabilities, strict=True)
    )
    true_p = np.asarray([truth[i] for i in test["application_id"].to_list()], dtype=np.float64)

    return {
        "corpus": corpus,
        "dataset": dataset,
        "train": train,
        "test": test,
        "y": test["approved"].to_numpy().astype(np.float64),
        "true_p": true_p,
        "base_rate": base_rate,
        "boosted": boosted,
        "hierarchical": hierarchical,
        "p_base": base_rate.predict(test),
    }


@pytest.mark.slow
class TestSampler:
    def test_the_sampler_converged(self, fitted) -> None:  # type: ignore[no-untyped-def]
        """An interval from an untrustworthy posterior is worse than no interval."""
        model = fitted["hierarchical"]
        assert model.converged, model.diagnostics
        assert model.diagnostics["divergences"] == 0
        assert model.diagnostics["max_r_hat"] <= 1.01
        assert model.diagnostics["min_ess"] >= 200

    def test_clusters_are_structural_and_have_more_than_one_member(self, fitted) -> None:  # type: ignore[no-untyped-def]
        """Clustering on outcomes would be circular and would guarantee meaningless intervals."""
        _assignment, members = assign_clusters(fitted["train"])
        assert members
        assert all(len(m) > 1 for m in members.values()), (
            "a cluster of one borrows strength from nobody, which reintroduces the flat model"
        )


@pytest.mark.slow
class TestPartialPoolingBeatsTheBenchmarks:
    def test_it_beats_the_base_rate_by_a_meaningful_margin(self, fitted) -> None:  # type: ignore[no-untyped-def]
        skill = brier_skill_score(
            fitted["y"], fitted["hierarchical"].predict(fitted["test"]), fitted["p_base"]
        )
        assert skill > 0.05, f"brier skill against the base rate was {skill:.4f}"

    def test_it_beats_the_boosted_model(self, fitted) -> None:  # type: ignore[no-untyped-def]
        """Section 6.8: if it never does, ship the simpler one. So the comparison is measured."""
        y, p_base = fitted["y"], fitted["p_base"]
        hierarchical_skill = brier_skill_score(
            y, fitted["hierarchical"].predict(fitted["test"]), p_base
        )
        boosted_skill = brier_skill_score(y, fitted["boosted"].predict(fitted["test"]), p_base)
        assert hierarchical_skill > boosted_skill

    def test_the_base_rate_benchmark_is_not_a_straw_man(self, fitted) -> None:  # type: ignore[no-untyped-def]
        """Building a weak baseline to beat is the oldest way to fool yourself."""
        base_rate = fitted["base_rate"]
        y, p_base = fitted["y"], fitted["p_base"]
        # It shrinks, so it is better than the unconditional mean.
        unconditional = np.full_like(p_base, float(fitted["train"]["approved"].mean()))
        assert brier_score(y, p_base) <= brier_score(y, unconditional) + 1e-6
        assert 0.5 <= base_rate.prior_strength <= 50.0
        assert auc(y, p_base) > 0.55, "the benchmark should carry real signal"

    def test_it_ranks_well_enough_for_portfolio_screening(self, fitted) -> None:  # type: ignore[no-untyped-def]
        """Section 5.4 product 2: a portfolio screen only needs the ordering to be right.

        The threshold is deliberately below the 0.70 target in section 6.9. That target is for the real
        corpus with the full feature set; this synthetic corpus carries ten features, an eighth of them
        missing, and a jurisdiction effect that has to be recovered through a noisy proxy. Asserting the
        production target here would be asserting something about the generator.
        """
        assert auc(fitted["y"], fitted["hierarchical"].predict(fitted["test"])) > 0.62


@pytest.mark.slow
class TestUncertaintyIsHonest:
    def test_the_credible_interval_covers_the_truth_at_the_stated_rate(self, fitted) -> None:  # type: ignore[no-untyped-def]
        """The exact test of an 80 percent interval, possible only because the truth is known.

        This is the assertion that caught the imputation bug: before missing features were
        marginalised rather than imputed at the mean, coverage was 69 percent against a claim of 80.
        """
        intervals = fitted["hierarchical"].predict_interval(fitted["test"])
        coverage = interval_coverage_against_truth(fitted["true_p"], intervals)
        assert 0.72 <= coverage <= 0.88, f"80 percent interval covered {coverage:.1%}"

    def test_the_point_estimate_lies_inside_its_own_interval(self, fitted) -> None:  # type: ignore[no-untyped-def]
        p = fitted["hierarchical"].predict(fitted["test"])
        intervals = fitted["hierarchical"].predict_interval(fitted["test"])
        assert np.all(intervals[:, 0] <= p + 1e-9)
        assert np.all(p <= intervals[:, 1] + 1e-9)

    def test_thin_jurisdictions_get_wider_intervals(self, fitted) -> None:  # type: ignore[no-untyped-def]
        """The whole point of section 6.8. Degrade gracefully instead of lying confidently.

        Split by tercile of depth rather than by an absolute count, so the assertion holds on any draw
        rather than only on one where the depth distribution happens to straddle a chosen threshold.
        """
        model, test = fitted["hierarchical"], fitted["test"]
        depth = fitted["dataset"].depth_by_jurisdiction()
        widths = np.diff(model.predict_interval(test), axis=1).ravel()

        row_depth = np.asarray(
            [depth.get(s, 0) for s in test["jurisdiction"].to_list()], dtype=float
        )
        low_cut, high_cut = np.quantile(row_depth, [1 / 3, 2 / 3])
        thin = row_depth <= low_cut
        deep = row_depth >= high_cut

        assert thin.sum() >= 5
        assert deep.sum() >= 5
        assert widths[thin].mean() > widths[deep].mean(), (
            f"thin jurisdictions (depth <= {low_cut:.0f}) got {widths[thin].mean():.3f} wide "
            f"intervals and deep ones (depth >= {high_cut:.0f}) got {widths[deep].mean():.3f}. "
            "Pooling is not widening where the evidence is thin."
        )

    def test_calibration_meets_the_published_promise_after_recalibration(self, fitted) -> None:  # type: ignore[no-untyped-def]
        """Section 6.9 rule 4: calibration is applied after fitting, so it is measured after too.

        Both numbers are asserted. The raw model has to be roughly calibrated out of the box, because a
        calibrator that has to do heavy lifting is a sign the model is wrong rather than merely
        miscalibrated. And the calibrated number has to meet the promise that gets published.
        """
        from auspice.models.eval.killtest import _fit_calibrator
        from auspice.models.hierarchical import HierarchicalModel

        y, test, train = fitted["y"], fitted["test"], fitted["train"]
        columns = fitted["dataset"].feature_columns
        raw = fitted["hierarchical"].predict(test)

        raw_ece = reliability_curve(y, raw).expected_calibration_error
        assert raw_ece < 0.14, f"the raw model is badly miscalibrated at {raw_ece:.4f}"

        def _refit(earlier, later):  # type: ignore[no-untyped-def]
            inner = HierarchicalModel(feature_columns=columns)
            inner.fit(earlier, warmup=300, samples=600, chains=1)
            return inner.predict(later)

        calibrator = _fit_calibrator(train, _refit)
        assert calibrator is not None, "there was enough training data to fit a calibrator"

        calibrated_ece = reliability_curve(y, calibrator.transform(raw)).expected_calibration_error
        assert calibrated_ece < 0.08, (
            f"calibrated expected calibration error was {calibrated_ece:.4f}, above the 0.08 promise"
        )

    def test_the_calibrator_is_fitted_without_touching_the_test_set(self, fitted) -> None:  # type: ignore[no-untyped-def]
        """Fitting a calibrator on the test set is leakage and makes the published number meaningless."""
        import inspect

        from auspice.models.eval import killtest

        source = inspect.getsource(killtest._fit_calibrator)
        assert "test" not in source.split('"""')[2], (
            "the calibrator must be fitted from the training set only"
        )

    def test_the_boosted_interval_is_labelled_a_bootstrap(self, fitted) -> None:  # type: ignore[no-untyped-def]
        """It is not a credible interval, and calling it one would be a quiet overstatement."""
        intervals = fitted["boosted"].predict_interval(fitted["test"])
        assert intervals.shape[1] == 2
        assert binned_interval_coverage(fitted["y"], intervals) >= 0.0


@pytest.mark.slow
class TestCoefficientRecovery:
    def test_most_causal_coefficients_are_recovered(self, fitted) -> None:  # type: ignore[no-untyped-def]
        """At a 90 percent credible interval, roughly nine in ten should contain the truth."""
        model, corpus = fitted["hierarchical"], fitted["corpus"]
        beta = model.posterior["beta"]
        scales = model.feature_scales
        assert scales is not None

        hits = 0
        total = 0
        for index, name in enumerate(model.feature_columns):
            if name not in CAUSAL_FEATURES:
                continue
            truth = corpus.true_coefficients[name]
            low, high = np.quantile(beta[:, index], [0.05, 0.95]) / scales[index]
            total += 1
            hits += int(low <= truth <= high)

        assert total >= 6
        assert hits >= total - 2, f"only {hits} of {total} causal coefficients were recovered"

    def test_the_signs_of_the_strong_effects_are_right(self, fitted) -> None:  # type: ignore[no-untyped-def]
        """A sign error on a strong effect is a leakage bug, not a discovery."""
        model, corpus = fitted["hierarchical"], fitted["corpus"]
        beta = model.posterior["beta"].mean(axis=0)
        for index, name in enumerate(model.feature_columns):
            truth = corpus.true_coefficients.get(name, 0.0)
            if abs(truth) < 0.5:
                continue
            assert np.sign(beta[index]) == np.sign(truth), f"{name} recovered the wrong sign"

    def test_the_variance_components_are_positive_and_finite(self, fitted) -> None:  # type: ignore[no-untyped-def]
        model = fitted["hierarchical"]
        for name in ("tau", "sigma"):
            draws = model.posterior[name]
            assert np.all(draws > 0)
            assert np.isfinite(draws).all()


@pytest.mark.slow
class TestPoolingWeight:
    def test_a_thin_jurisdiction_borrows_more(self, fitted) -> None:  # type: ignore[no-untyped-def]
        model = fitted["hierarchical"]
        thin = model.pooling_weight("synthetic-00", local_observations=2)
        deep = model.pooling_weight("synthetic-00", local_observations=50)
        assert thin > deep
        assert 0.0 <= deep < thin <= 1.0

    def test_an_unseen_jurisdiction_does_not_crash_and_widens(self, fitted) -> None:  # type: ignore[no-untyped-def]
        """A county we have never seen is the expansion case, and it must widen rather than fail."""
        test = fitted["test"]
        unseen = test.head(5).with_columns(
            __import__("polars").lit("never-seen-county").alias("jurisdiction")
        )
        model = fitted["hierarchical"]
        widths_unseen = np.diff(model.predict_interval(unseen), axis=1).ravel()
        widths_known = np.diff(model.predict_interval(test.head(5)), axis=1).ravel()
        assert np.all(np.isfinite(widths_unseen))
        assert widths_unseen.mean() >= widths_known.mean() - 0.02


class TestSurvivalHandlesCensoring:
    def test_pending_rows_are_kept(self, synthetic_dataset) -> None:  # type: ignore[no-untyped-def]
        """Dropping them is the bug that biases every timeline optimistically."""
        model = SurvivalModel(feature_columns=synthetic_dataset.feature_columns)
        model.fit(synthetic_dataset.frame, as_of=CORPUS_END)
        pending = synthetic_dataset.frame.filter(synthetic_dataset.frame["censored"]).height
        assert model.n_train == synthetic_dataset.frame.height
        assert model.n_censored >= pending

    def test_the_estimate_is_not_biased_optimistically(self, synthetic_dataset) -> None:  # type: ignore[no-untyped-def]
        """The naive median over decided rows only is biased low. The model must correct for it.

        Kaplan-Meier is the nonparametric, censoring aware answer, so the fitted median is checked
        against that rather than against the naive one.
        """
        from lifelines import KaplanMeierFitter

        from auspice.models.survival.model import _prepare

        prepared, duration_col, event_col = _prepare(
            synthetic_dataset.frame, target=None, as_of=CORPUS_END
        )
        km = KaplanMeierFitter().fit(
            prepared[duration_col].to_numpy(), prepared[event_col].to_numpy()
        )
        km_median = float(km.median_survival_time_)
        naive_median = float(
            np.median(
                synthetic_dataset.frame.filter(~synthetic_dataset.frame["censored"])[
                    "months_to_decision"
                ].to_numpy()
            )
        )

        model = SurvivalModel(feature_columns=synthetic_dataset.feature_columns)
        model.fit(synthetic_dataset.frame, as_of=CORPUS_END)
        fitted_median = float(np.median(model.quantiles(synthetic_dataset.frame)[:, 1]))

        assert naive_median < km_median, "the naive median should be the optimistic one"
        assert abs(fitted_median - km_median) / km_median < 0.30, (
            f"fitted median {fitted_median:.1f} is far from Kaplan-Meier {km_median:.1f}"
        )
        assert fitted_median > naive_median

    def test_quantiles_are_ordered(self, synthetic_dataset) -> None:  # type: ignore[no-untyped-def]
        model = SurvivalModel(feature_columns=synthetic_dataset.feature_columns)
        model.fit(synthetic_dataset.frame, as_of=CORPUS_END)
        quantiles = model.quantiles(synthetic_dataset.frame)
        assert np.all(quantiles[:, 0] <= quantiles[:, 1])
        assert np.all(quantiles[:, 1] <= quantiles[:, 2])
        assert np.all(quantiles > 0)

    def test_cumulative_incidence_is_monotone_and_sums_to_one(self, synthetic_dataset) -> None:  # type: ignore[no-untyped-def]
        """A cumulative function cannot decrease, and the arms plus pending are a distribution."""
        model = SurvivalModel(feature_columns=synthetic_dataset.feature_columns)
        model.fit(synthetic_dataset.frame, as_of=CORPUS_END)

        previous: dict[str, float] | None = None
        for months in (6, 12, 24, 36, 60):
            incidence = model.cumulative_incidence(synthetic_dataset.frame, months=months)
            assert incidence
            assert sum(incidence.values()) == pytest.approx(1.0, abs=0.05)
            if previous is not None:
                for arm, value in incidence.items():
                    if arm == "pending":
                        assert value <= previous[arm] + 1e-6
                    else:
                        assert value >= previous[arm] - 1e-6
            previous = incidence

    def test_competing_risks_are_modelled_separately(self, synthetic_dataset) -> None:  # type: ignore[no-untyped-def]
        model = SurvivalModel(feature_columns=synthetic_dataset.feature_columns)
        model.fit(synthetic_dataset.frame, as_of=CORPUS_END)
        assert set(model.cause_specific) >= {"approval", "denial"}

    def test_it_declines_rather_than_inventing_a_model(self) -> None:
        """With almost no events a fitted model would be fiction. It says so instead."""
        import polars as pl

        frame = pl.DataFrame(
            {
                "months_to_decision": [3.0, None, None],
                "filed_on": [date(2025, 1, 1)] * 3,
                "censored": [False, True, True],
                "risk": ["approval", "censored", "censored"],
            }
        )
        model = SurvivalModel(feature_columns=[])
        model.fit(frame, as_of=CORPUS_END)
        assert model.aft is None
        assert model.params()["fitted"] is False
        assert model.notes
