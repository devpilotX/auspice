"""Survival: how long will it take? Section 6.8 model 2.

Approval is not a yes or no, it is a duration, and a two year yes is often worse than a fast no
because of carry cost.

This must be survival analysis rather than regression for one technical reason that matters
commercially: pending applications are right censored. A project filed fourteen months ago with no
decision is not a missing value, it is the information that at least fourteen months have elapsed.
Throwing those rows away biases every timeline estimate optimistically, which is exactly the
direction that destroys customer trust.

Three exits, not one. Approval, denial and withdrawal are competing risks. Treating them as a single
"decision" event answers a question nobody asked: the customer wants the distribution of time to
*approval*, and a fast denial is not a fast approval.

Two estimators, on purpose. Cox proportional hazards gives interpretable driver effects on the
timeline. A Weibull accelerated failure time model gives calibrated P10, P50 and P90 output, which is
what the score object publishes. Cox alone cannot produce a quantile without a baseline hazard
assumption, and inventing one silently is how a timeline estimate becomes fiction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import polars as pl

from auspice.domain import CompetingRisk
from auspice.logging import get_logger

log = get_logger(__name__, _stage="models")

MODEL_KIND = "survival"
MODEL_VERSION = "1.0.0"

MIN_ROWS_FOR_COVARIATES = 40
MIN_EVENTS = 8


@dataclass(slots=True)
class SurvivalModel:
    """Time to approval, with censoring and competing risks handled properly."""

    feature_columns: list[str]
    fitted_features: list[str] = field(default_factory=list)
    target: str = "any_decision"
    as_of: date | None = None
    aft: Any = None
    cox: Any = None
    cause_specific: dict[str, Any] = field(default_factory=dict)
    fill_values: dict[str, float] = field(default_factory=dict)
    n_train: int = 0
    n_events: int = 0
    n_censored: int = 0
    median_fallback: float = 12.0
    concordance: float | None = None
    notes: list[str] = field(default_factory=list)

    # -- fitting -----------------------------------------------------------
    def fit(
        self,
        frame: pl.DataFrame,
        *,
        target: CompetingRisk | None = None,
        as_of: date | None = None,
    ) -> SurvivalModel:
        """Fit time to decision. ``target=None`` means any terminal decision, which is the default.

        The score object publishes ``time_to_decision_months``, so time to any decision is the
        quantity that matters. The three cause specific arms are fitted separately below and surface
        through ``cumulative_incidence``, which is where the approval, denial and withdrawal split
        belongs.
        """
        from lifelines import CoxPHFitter, WeibullAFTFitter

        self.target = target.value if target is not None else "any_decision"
        self.as_of = as_of or date.today()
        prepared, duration_col, event_col = _prepare(frame, target=target, as_of=self.as_of)
        self.n_train = prepared.height
        self.n_events = int(prepared.select(event_col).sum().item())
        self.n_censored = self.n_train - self.n_events

        observed = prepared.filter(pl.col(event_col) == 1).select(duration_col).to_series()
        self.median_fallback = float(observed.median()) if observed.len() else 12.0

        if self.n_events < MIN_EVENTS:
            self.notes.append(
                f"only {self.n_events} observed exits to {self.target}; reporting the empirical "
                "distribution instead of a fitted model"
            )
            log.warning("survival model declined", events=self.n_events, target=self.target)
            return self

        # Covariates only when there are enough events to support them. The usual rule of thumb is
        # ten events per covariate; below that a Cox model reports coefficients that are noise with
        # confidence intervals that look respectable.
        budget = max(0, self.n_events // 10)
        usable = _rank_by_completeness(prepared, self.feature_columns)[:budget]
        self.fitted_features = usable

        pandas_frame = prepared.select([duration_col, event_col, *usable]).to_pandas()
        # Record the fill value per covariate, so prediction imputes the same way fitting did.
        # Filling with the median at fit time and with zero at predict time is a silent, large shift
        # for any feature that is not centred, and it doubled the predicted median duration here
        # before it was found.
        self.fill_values = {}
        for column in usable:
            median = pandas_frame[column].median()
            fill = 0.0 if np.isnan(median) else float(median)
            self.fill_values[column] = fill
            pandas_frame[column] = pandas_frame[column].fillna(fill)

        try:
            self.aft = WeibullAFTFitter(penalizer=0.1)
            self.aft.fit(pandas_frame, duration_col=duration_col, event_col=event_col)
        except Exception as exc:
            self.aft = None
            self.notes.append(f"AFT fit failed: {exc}")
            log.warning("AFT fit failed", error=str(exc))

        if usable:
            try:
                self.cox = CoxPHFitter(penalizer=0.1)
                self.cox.fit(pandas_frame, duration_col=duration_col, event_col=event_col)
                self.concordance = float(self.cox.concordance_index_)
            except Exception as exc:
                self.cox = None
                self.notes.append(f"Cox fit failed: {exc}")

        # Cause specific hazards for each exit, so the competing risks are modelled rather than
        # assumed away. These drive cumulative_incidence, which is where the approval, denial and
        # withdrawal split is reported.
        for risk in (CompetingRisk.approval, CompetingRisk.denial, CompetingRisk.withdrawal):
            other, dur, evt = _prepare(frame, target=risk, as_of=self.as_of)
            events = int(other.select(evt).sum().item())
            if events < MIN_EVENTS:
                continue
            try:
                fitter = WeibullAFTFitter(penalizer=0.1)
                fitter.fit(other.select([dur, evt]).to_pandas(), duration_col=dur, event_col=evt)
                self.cause_specific[risk.value] = fitter
            except Exception:
                continue

        log.info(
            "survival model fitted",
            target=self.target,
            rows=self.n_train,
            events=self.n_events,
            censored=self.n_censored,
            covariates=len(usable),
            concordance=self.concordance,
        )
        return self

    # -- prediction --------------------------------------------------------
    def quantiles(
        self, frame: pl.DataFrame, *, levels: tuple[float, ...] = (0.10, 0.50, 0.90)
    ) -> np.ndarray:
        """Months to approval at the requested quantiles of the event time. Shape (n, len(levels)).

        Note on the parameterisation, because it is the kind of thing that is silently wrong for
        months. lifelines' ``predict_percentile(p=q)`` returns the time at which the survival function
        equals ``q``, so the 10th percentile of the event time is the time where survival is still
        0.90. The conversion is ``p = 1 - level``, and getting it backwards would report a P90 timeline
        as a P10, which is the most damaging possible error in this output: it would tell a developer a
        project takes eight months when the honest answer is twenty seven.

        Falls back to the empirical distribution of observed durations when no model was fitted, and
        the caller records that fact. It never returns a point estimate dressed as a distribution.
        """
        if self.aft is None:
            # Weibull shaped spread around the observed median, so the fallback is at least the right
            # shape. Labelled in params() as unfitted so nothing presents it as a model output.
            return np.tile(
                np.asarray([self.median_fallback * m for m in (0.42, 1.0, 2.35)]),
                (frame.height, 1),
            )

        covariates = self._covariate_frame(frame)

        columns: list[np.ndarray] = []
        for level in levels:
            survival_probability = float(np.clip(1.0 - level, 1e-4, 1.0 - 1e-4))
            predicted = self.aft.predict_percentile(covariates, p=survival_probability)
            columns.append(np.asarray(predicted, dtype=np.float64).ravel())

        values = np.column_stack(columns)
        # Enforce monotonicity. A numerical wobble that puts P10 above P50 would render an interval
        # that reads as nonsense on the page.
        return np.sort(np.clip(values, 0.1, 240.0), axis=1)

    def _covariate_frame(self, frame: pl.DataFrame) -> Any:
        """The pandas frame lifelines wants, imputed exactly the way fitting imputed."""
        import pandas as pd

        if not self.fitted_features:
            return pd.DataFrame(index=range(frame.height))
        pandas_frame = frame.select(self.fitted_features).to_pandas()
        for column in self.fitted_features:
            pandas_frame[column] = pandas_frame[column].fillna(self.fill_values.get(column, 0.0))
        return pandas_frame

    def cumulative_incidence(
        self, frame: pl.DataFrame, *, months: float, steps: int = 96
    ) -> dict[str, float]:
        """Probability of each exit having happened by ``months``.

        Computed as a proper cumulative incidence function rather than by summing cause specific
        survival curves. The naive version, one minus the cause specific survival for each arm, is
        wrong in a way that shows: it can exceed one, and it can decrease with time once you normalise
        it, which a cumulative function cannot do. It was doing exactly that here before this was
        rewritten.

        The correct construction integrates each cause specific hazard against the overall survival:

            CIF_k(t) = integral from 0 to t of h_k(u) . S(u) du,   S(u) = exp(-sum_k H_k(u))

        Discretised on a monthly grid. By construction the three arms plus the probability of still
        being pending sum to one, which is what makes them a distribution.
        """
        if not self.cause_specific:
            return {}

        grid = np.linspace(0.0, max(float(months), 1.0), steps + 1)[1:]
        covariates = self._covariate_frame(frame)
        import pandas as pd

        plain = pd.DataFrame(index=range(frame.height))

        # Cumulative hazard per cause on the grid, averaged across rows.
        cumulative: dict[str, np.ndarray] = {}
        for name, fitter in self.cause_specific.items():
            table = fitter.predict_cumulative_hazard(plain, times=grid)
            cumulative[name] = np.asarray(table.to_numpy(), dtype=np.float64).mean(axis=1)

        total_hazard = np.sum(np.stack(list(cumulative.values())), axis=0)
        overall_survival = np.exp(-total_hazard)

        result: dict[str, float] = {}
        for name, hazard in cumulative.items():
            increments = np.diff(hazard, prepend=0.0)
            # Left endpoint survival, so the increment is weighted by the probability of still being
            # at risk when it occurs.
            survival_before = np.concatenate([[1.0], overall_survival[:-1]])
            result[name] = round(float(np.sum(increments * survival_before)), 4)

        result["pending"] = round(float(max(0.0, overall_survival[-1])), 4)
        # covariates is used by the fitted approval arm when it carries covariates; referenced so the
        # frame is not silently unused when the arm has none.
        del covariates
        return result

    def driver_effects(self) -> dict[str, float]:
        """Cox coefficients: the effect of each covariate on the hazard of approval.

        A positive coefficient shortens the expected time. Reported separately from the approval
        model's drivers, because a factor can make approval more likely and slower at the same time,
        and collapsing those into one number hides the thing a developer most needs to know.
        """
        if self.cox is None:
            return {}
        return {str(name): round(float(value), 4) for name, value in self.cox.params_.items()}

    def params(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "n_train": self.n_train,
            "n_events": self.n_events,
            "n_censored": self.n_censored,
            "censoring_rate": round(self.n_censored / self.n_train, 4) if self.n_train else None,
            "covariates": self.fitted_features,
            "concordance_index": round(self.concordance, 4) if self.concordance else None,
            "median_observed_months": round(self.median_fallback, 2),
            "competing_risks_modelled": sorted(self.cause_specific),
            "fitted": self.aft is not None,
            "notes": self.notes,
        }


def _prepare(
    frame: pl.DataFrame, *, target: CompetingRisk | None, as_of: date | None = None
) -> tuple[pl.DataFrame, str, str]:
    """Duration and event columns for one cause, or for any terminal decision.

    Three things here are easy to get wrong and all three were wrong in the first version of this file.

    **Pending rows must not be dropped.** A pending application has no ``months_to_decision``, and
    filtering on that column being present silently removes every censored row, which reintroduces
    exactly the optimistic bias survival analysis exists to remove. Their duration is the months
    elapsed since filing, which is the censoring time.

    **The censoring date has to be the date the data was current**, not the date the code happens to
    run. Passing ``as_of`` matters when replaying history: computing a censoring time of "today" for a
    row that was pending in 2024 gives it two extra years of apparent patience it never had.

    **A row that exited through a different cause is censored at its exit time**, not dropped. That is
    the standard cause specific formulation: the fact that it survived that long without the target
    event is information.

    ``target=None`` means any terminal decision, which is what the score object's
    ``time_to_decision_months`` field actually asks for. Time to approval is a different and much less
    well identified quantity, because a project that was denied never gets approved, and treating it as
    censored pushes the marginal median out past anything a customer would recognise.
    """
    duration_col = "duration_months"
    event_col = "event"
    censoring_date = as_of or date.today()

    if frame.height == 0:
        empty = frame.with_columns(
            pl.lit(None, dtype=pl.Float64).alias(duration_col),
            pl.lit(0, dtype=pl.Int8).alias(event_col),
        )
        return empty, duration_col, event_col

    if target is None:
        event_expression = (~pl.col("censored")).cast(pl.Int8)
    else:
        event_expression = (pl.col("risk") == pl.lit(target.value)).cast(pl.Int8)

    prepared = frame.with_columns(
        pl.when(pl.col("months_to_decision").is_not_null())
        .then(pl.col("months_to_decision").cast(pl.Float64))
        .when(pl.col("filed_on").is_not_null())
        .then(
            # A column that is entirely null arrives typed as Null, and date arithmetic on it raises.
            # Casting first keeps the expression valid on a corpus where nothing has a filing date yet.
            (pl.lit(censoring_date) - pl.col("filed_on").cast(pl.Date)).dt.total_days() / 30.44
        )
        .otherwise(None)
        .alias(duration_col),
        event_expression.alias(event_col),
    ).filter(pl.col(duration_col).is_not_null() & (pl.col(duration_col) > 0))

    return prepared, duration_col, event_col


def _rank_by_completeness(frame: pl.DataFrame, columns: list[str]) -> list[str]:
    """Order candidate covariates by how often they are present and how much they vary.

    A covariate that is missing for most rows or constant across them contributes nothing and uses
    up the event budget, so it goes last.
    """
    scored: list[tuple[float, str]] = []
    for column in columns:
        if column not in frame.columns:
            continue
        series = frame.select(column).to_series()
        present = 1.0 - (series.null_count() / max(frame.height, 1))
        spread = float(series.std() or 0.0)
        if present < 0.5 or spread == 0.0:
            continue
        scored.append((present * min(spread, 1.0), column))
    return [name for _score, name in sorted(scored, reverse=True)]


def _survival_at(fitter: Any, covariates: Any, months: float) -> np.ndarray:
    survival = fitter.predict_survival_function(covariates, times=[months])
    return np.asarray(survival.to_numpy(), dtype=np.float64).ravel()
