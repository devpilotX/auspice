"""The base rate model.

Section 6.9 validation rule 5: a base rate model is a permanent tracked baseline, and if the
sophisticated model cannot beat "the historical approval rate for this use class in this county", it
must not ship.

This is that model, and it is deliberately as good as a base rate can be, not a straw man. Building a
weak baseline to beat is the oldest way to fool yourself in applied statistics. So it uses a
hierarchical shrinkage of its own: a jurisdiction with forty decisions is scored on its own record, a
jurisdiction with two is shrunk toward its state, and a jurisdiction with none falls back to the
global rate.

That shrinkage is empirical Bayes with a Beta prior fitted by moment matching, which is the standard
answer and takes about thirty lines. The hierarchical model in ``models/hierarchical`` has to beat
this, not a coin flip.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import polars as pl

from auspice.logging import get_logger

log = get_logger(__name__, _stage="models")

MODEL_KIND = "base_rate"
MODEL_VERSION = "1.0.0"

# Below this many observations a level is not allowed to speak for itself at all.
MIN_LEVEL_OBSERVATIONS = 1


@dataclass(slots=True)
class BaseRateModel:
    """Approval rate by jurisdiction and use class, shrunk toward wider levels."""

    global_rate: float = 0.5
    prior_strength: float = 4.0
    by_juris_use: dict[tuple[str, ...], tuple[int, int]] = field(default_factory=dict)
    by_region_use: dict[tuple[str, ...], tuple[int, int]] = field(default_factory=dict)
    by_use: dict[str, tuple[int, int]] = field(default_factory=dict)
    n_train: int = 0

    # -- fitting -----------------------------------------------------------
    def fit(self, frame: pl.DataFrame) -> BaseRateModel:
        approved = frame.select("approved").to_numpy().ravel().astype(float)
        self.n_train = int(frame.height)
        self.global_rate = float(approved.mean()) if frame.height else 0.5

        self.by_juris_use = _tally(frame, ("jurisdiction", "use_class"))
        self.by_region_use = _tally(frame, ("region", "use_class"))
        self.by_use = {k[0]: v for k, v in _tally(frame, ("use_class",)).items()}

        self.prior_strength = _fit_prior_strength(self.by_juris_use, self.global_rate)

        log.info(
            "base rate fitted",
            rows=self.n_train,
            global_rate=round(self.global_rate, 4),
            prior_strength=round(self.prior_strength, 2),
            jurisdiction_cells=len(self.by_juris_use),
        )
        return self

    # -- prediction --------------------------------------------------------
    def predict_one(self, *, jurisdiction: str, region: str, use_class: str) -> tuple[float, float]:
        """Returns (probability, effective observation count).

        The second value is what the abstention rule and the pooling note consume: it says how much
        of this number came from the jurisdiction's own record.
        """
        # Walk from the most specific level outward, shrinking at each step.
        use_prior = _shrunk(self.by_use.get(use_class), self.global_rate, self.prior_strength)
        region_prior = _shrunk(
            self.by_region_use.get((region, use_class)), use_prior, self.prior_strength
        )
        local = self.by_juris_use.get((jurisdiction, use_class))
        probability = _shrunk(local, region_prior, self.prior_strength)
        observations = float(local[1]) if local else 0.0
        return probability, observations

    def predict(self, frame: pl.DataFrame) -> np.ndarray:
        return np.asarray(
            [
                self.predict_one(
                    jurisdiction=str(row["jurisdiction"]),
                    region=str(row["region"]),
                    use_class=str(row["use_class"]),
                )[0]
                for row in frame.iter_rows(named=True)
            ],
            dtype=np.float64,
        )

    def pooling_weight(self, *, jurisdiction: str, use_class: str) -> float:
        """Share of the estimate that came from outside this jurisdiction.

        Section 8.4 uses this in the abstention rule, and section 5.6 rule 4 requires disclosing it
        to the customer. An honest number here is uncomfortable and it is what makes the estimate
        credible.
        """
        local = self.by_juris_use.get((jurisdiction, use_class))
        n = float(local[1]) if local else 0.0
        return float(self.prior_strength / (self.prior_strength + n))

    def params(self) -> dict[str, Any]:
        return {
            "global_rate": round(self.global_rate, 6),
            "prior_strength": round(self.prior_strength, 4),
            "jurisdiction_cells": len(self.by_juris_use),
            "region_cells": len(self.by_region_use),
            "use_class_cells": len(self.by_use),
            "n_train": self.n_train,
        }


def _tally(frame: pl.DataFrame, keys: tuple[str, ...]) -> dict[tuple[str, ...], tuple[int, int]]:
    """Per cell (approved, total)."""
    if frame.height == 0:
        return {}
    grouped = (
        frame.group_by(list(keys))
        .agg(pl.col("approved").sum().alias("approved"), pl.len().alias("total"))
        .iter_rows(named=True)
    )
    out: dict[tuple[str, ...], tuple[int, int]] = {}
    for row in grouped:
        key = tuple(str(row[k]) for k in keys)
        out[key] = (int(row["approved"]), int(row["total"]))
    return out


def _shrunk(cell: tuple[int, int] | None, prior_mean: float, strength: float) -> float:
    """Posterior mean of a Beta binomial with mean ``prior_mean`` and weight ``strength``."""
    if cell is None or cell[1] < MIN_LEVEL_OBSERVATIONS:
        return float(prior_mean)
    successes, total = cell
    alpha = prior_mean * strength
    beta = (1.0 - prior_mean) * strength
    return float((successes + alpha) / (total + alpha + beta))


def _fit_prior_strength(cells: dict[tuple[str, ...], tuple[int, int]], global_rate: float) -> float:
    """Moment matched Beta prior strength.

    If the observed variance between jurisdictions is no larger than binomial sampling noise would
    explain, there is no evidence that jurisdictions differ, and the prior should be strong enough to
    shrink almost everything to the global rate. If the between jurisdiction variance is large, the
    prior should be weak and let local records speak.

    Falls back to a strength of 4, roughly "four decisions of evidence", when there is not enough
    data to estimate the variance at all. That is a deliberate default: it means a county with four
    decisions is weighted equally against its state, which matches how a careful analyst would read
    a four decision record.
    """
    usable = [(a, n) for a, n in cells.values() if n >= 2]
    if len(usable) < 3:
        return 4.0

    rates = np.asarray([a / n for a, n in usable], dtype=np.float64)
    counts = np.asarray([n for _a, n in usable], dtype=np.float64)

    observed_variance = float(rates.var(ddof=1))
    # Expected variance from binomial noise alone, at the global rate.
    sampling_variance = float(np.mean(global_rate * (1.0 - global_rate) / counts))
    between_variance = observed_variance - sampling_variance

    if between_variance <= 1e-6:
        # No evidence that jurisdictions differ beyond noise. Shrink hard.
        return 50.0

    # Beta moment matching: var = mu(1-mu)/(strength+1)
    strength = global_rate * (1.0 - global_rate) / between_variance - 1.0
    return float(np.clip(strength, 0.5, 50.0))
