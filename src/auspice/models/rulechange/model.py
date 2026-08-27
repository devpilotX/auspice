"""Will the rules change first? Section 6.8 model 3.

Section 6.8 makes this a distinct model rather than a feature, for two reasons: it is the risk humans
most consistently fail to price, and it produces the most valuable alert in section 6.11.

It answers a different question from the approval model, on a different unit of analysis. The approval
model asks about an application. This asks about a jurisdiction and a window: given what the county
looks like today, what is the probability it adopts a restriction on this use class before a decision
is reached?

The estimator is a discrete time hazard on jurisdiction months. Each jurisdiction contributes one row
per month it was under observation and had not yet restricted the use class; the outcome is whether it
adopted a restriction that month. That formulation handles two things a plain classifier cannot: a
county that has not restricted yet is censored rather than a negative example, and the hazard is
allowed to depend on how long the county has been exposed.

With a corpus this size the model is deliberately small. Four covariates, a logistic link, and a
Firth style penalty so that a perfectly separating covariate produces a large coefficient rather than
an infinite one. Anything more elaborate would fit the noise in a few hundred jurisdiction months.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.engine import Connection

from auspice.logging import get_logger

log = get_logger(__name__, _stage="models")

MODEL_KIND = "rule_change"
MODEL_VERSION = "1.0.0"

RESTRICTIVE_KINDS = ["moratorium", "overlay_district", "interim_control"]
MIN_EVENTS = 4
MAX_ITERATIONS = 200
RIDGE = 1.0


_PANEL_SQL = text(
    """
    WITH months AS (
        SELECT generate_series(
            date_trunc('month', CAST(:start AS date)),
            date_trunc('month', CAST(:end AS date)),
            interval '1 month'
        )::date AS month_start
    ),
    restrictions AS (
        SELECT
            i.jurisdiction_id,
            date_trunc('month', i.adopted_on)::date AS month_start
        FROM instrument i
        WHERE i.kind = ANY(:restrictive_kinds)
          AND i.adopted_on IS NOT NULL
          AND (
              cardinality(i.applies_to_use_classes) = 0
              OR :use_class = ANY(i.applies_to_use_classes)
          )
    ),
    first_restriction AS (
        SELECT jurisdiction_id, min(month_start) AS first_month
        FROM restrictions GROUP BY jurisdiction_id
    )
    SELECT
        j.id                                    AS jurisdiction_id,
        j.slug,
        m.month_start,
        (fr.first_month = m.month_start)        AS restricted_this_month,
        -- Neighbours that had already restricted before this month. Section 6.7 group D:
        -- opposition tactics diffuse geographically faster than policy does.
        (
            SELECT count(DISTINCT n.id)
            FROM jurisdiction n
            JOIN first_restriction nfr ON nfr.jurisdiction_id = n.id
            WHERE n.id <> j.id
              AND n.boundary IS NOT NULL
              AND j.boundary IS NOT NULL
              AND ST_Intersects(j.boundary, n.boundary)
              AND nfr.first_month < m.month_start
        )                                       AS neighbours_restricted,
        -- Any restriction anywhere in the same state before this month.
        (
            SELECT count(DISTINCT s.id)
            FROM jurisdiction s
            JOIN first_restriction sfr ON sfr.jurisdiction_id = s.id
            WHERE s.id <> j.id
              AND s.region = j.region
              AND sfr.first_month < m.month_start
        )                                       AS state_restricted,
        (
            SELECT count(*)
            FROM objection o
            WHERE o.jurisdiction_id = j.id
              AND o.observed_on IS NOT NULL
              AND o.observed_on < m.month_start
              AND o.observed_on >= (m.month_start - interval '24 months')
        )                                       AS objections_24m,
        (
            SELECT count(*)
            FROM application a
            WHERE a.jurisdiction_id = j.id
              AND a.use_class = :use_class
              AND a.filed_on IS NOT NULL
              AND a.filed_on < m.month_start
              AND a.filed_on >= (m.month_start - interval '24 months')
        )                                       AS filings_24m,
        (
            SELECT min(e.election_date)
            FROM election e
            JOIN decision_body b ON b.id = e.body_id
            WHERE b.jurisdiction_id = j.id AND e.election_date >= m.month_start
        )                                       AS next_election,
        (j.legal_framework = 'home_rule')       AS home_rule,
        fr.first_month
    FROM jurisdiction j
    CROSS JOIN months m
    LEFT JOIN first_restriction fr ON fr.jurisdiction_id = j.id
    WHERE (fr.first_month IS NULL OR m.month_start <= fr.first_month)
    ORDER BY j.slug, m.month_start
    """
)

COVARIATES = (
    "neighbours_restricted",
    "state_restricted",
    "objection_pressure",
    "election_within_12m",
)


@dataclass(slots=True)
class RuleChangeModel:
    """Monthly hazard of a jurisdiction restricting a use class."""

    use_class: str
    coefficients: np.ndarray | None = None
    intercept: float = 0.0
    n_rows: int = 0
    n_events: int = 0
    n_jurisdictions: int = 0
    baseline_monthly_hazard: float = 0.0
    notes: list[str] = field(default_factory=list)

    # -- fitting -----------------------------------------------------------
    def fit(self, conn: Connection, *, start: date, end: date) -> RuleChangeModel:
        panel = _load_panel(conn, use_class=self.use_class, start=start, end=end)
        self.n_rows = len(panel["y"])
        self.n_events = int(panel["y"].sum())
        self.n_jurisdictions = panel["n_jurisdictions"]

        if self.n_rows == 0:
            self.notes.append("no jurisdiction months in the observation window")
            return self

        self.baseline_monthly_hazard = float(panel["y"].mean())

        if self.n_events < MIN_EVENTS:
            self.notes.append(
                f"only {self.n_events} restriction events on record; reporting the pooled monthly "
                f"hazard of {self.baseline_monthly_hazard:.4f} without covariates"
            )
            log.warning("rule change model declined covariates", events=self.n_events)
            self.intercept = _logit(self.baseline_monthly_hazard)
            return self

        x = panel["x"]
        y = panel["y"]
        design = np.column_stack([np.ones(len(y)), x])
        weights = _fit_penalised_logistic(design, y)
        self.intercept = float(weights[0])
        self.coefficients = weights[1:]

        log.info(
            "rule change model fitted",
            use_class=self.use_class,
            jurisdiction_months=self.n_rows,
            events=self.n_events,
            baseline_monthly_hazard=round(self.baseline_monthly_hazard, 5),
        )
        return self

    # -- prediction --------------------------------------------------------
    def monthly_hazard(self, covariates: dict[str, float]) -> float:
        if self.coefficients is None:
            return float(np.clip(self.baseline_monthly_hazard, 1e-6, 0.5))
        x = np.asarray([float(covariates.get(name, 0.0)) for name in COVARIATES], dtype=np.float64)
        return float(np.clip(_sigmoid(self.intercept + float(x @ self.coefficients)), 1e-6, 0.9))

    def probability_before(self, covariates: dict[str, float], *, months: float) -> float:
        """Probability of at least one restriction within ``months``.

        One minus the survival of a constant monthly hazard. Held constant on purpose: with this many
        events, letting the hazard vary with exposure time would be fitting a shape to four points.
        The assumption is stated in docs/METHODOLOGY.md rather than buried.
        """
        hazard = self.monthly_hazard(covariates)
        horizon = max(float(months), 0.0)
        return float(np.clip(1.0 - (1.0 - hazard) ** horizon, 0.0, 1.0))

    def covariates_for(
        self, conn: Connection, *, jurisdiction_id: int, as_of: date
    ) -> dict[str, float]:
        """Read the covariates for one jurisdiction as of one date."""
        row = (
            conn.execute(
                _PANEL_SQL.bindparams(
                    start=as_of.replace(day=1),
                    end=as_of.replace(day=1),
                    use_class=self.use_class,
                    restrictive_kinds=RESTRICTIVE_KINDS,
                )
            )
            .mappings()
            .all()
        )
        for record in row:
            if int(record["jurisdiction_id"]) == jurisdiction_id:
                return _covariates_from_record(record, as_of=as_of)
        return dict.fromkeys(COVARIATES, 0.0)

    def params(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "use_class": self.use_class,
            "jurisdiction_months": self.n_rows,
            "events": self.n_events,
            "jurisdictions": self.n_jurisdictions,
            "baseline_monthly_hazard": round(self.baseline_monthly_hazard, 6),
            "intercept": round(self.intercept, 4),
            "notes": self.notes,
        }
        if self.coefficients is not None:
            out["coefficients"] = {
                name: round(float(value), 4)
                for name, value in zip(COVARIATES, self.coefficients, strict=True)
            }
        return out


def _load_panel(conn: Connection, *, use_class: str, start: date, end: date) -> dict[str, Any]:
    records = (
        conn.execute(
            _PANEL_SQL.bindparams(
                start=start, end=end, use_class=use_class, restrictive_kinds=RESTRICTIVE_KINDS
            )
        )
        .mappings()
        .all()
    )

    rows: list[list[float]] = []
    outcomes: list[int] = []
    jurisdictions: set[int] = set()

    for record in records:
        jurisdictions.add(int(record["jurisdiction_id"]))
        covariates = _covariates_from_record(record, as_of=record["month_start"])
        rows.append([covariates[name] for name in COVARIATES])
        outcomes.append(1 if record["restricted_this_month"] else 0)

    return {
        "x": np.asarray(rows, dtype=np.float64) if rows else np.zeros((0, len(COVARIATES))),
        "y": np.asarray(outcomes, dtype=np.float64),
        "n_jurisdictions": len(jurisdictions),
    }


def _covariates_from_record(record: Any, *, as_of: date) -> dict[str, float]:
    next_election = record["next_election"]
    months_to_election = (
        (next_election.toordinal() - as_of.toordinal()) / 30.44 if next_election else None
    )
    filings = float(record["filings_24m"] or 0)
    objections = float(record["objections_24m"] or 0)
    return {
        "neighbours_restricted": float(record["neighbours_restricted"] or 0),
        "state_restricted": float(record["state_restricted"] or 0),
        # Objections per filing, so a busy county is not mistaken for a hostile one.
        "objection_pressure": objections / filings if filings else objections,
        "election_within_12m": 1.0
        if months_to_election is not None and months_to_election <= 12.0
        else 0.0,
    }


def _sigmoid(x: float | np.ndarray) -> Any:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30.0, 30.0)))


def _logit(p: float) -> float:
    clipped = float(np.clip(p, 1e-6, 1 - 1e-6))
    return float(np.log(clipped / (1.0 - clipped)))


def _fit_penalised_logistic(design: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Ridge penalised logistic regression by Newton iteration.

    The penalty is not optional here. Rule change events are rare, so a covariate that happens to be
    present for every event and absent for every non event separates the data perfectly, and
    unpenalised maximum likelihood sends its coefficient to infinity. The published number would then
    be exactly 0 or 1 for any county with that covariate, which is not a forecast.

    The intercept is left unpenalised, because shrinking it toward zero would shrink the baseline
    hazard toward one half, and the baseline monthly hazard of a county adopting a moratorium is
    nowhere near one half.
    """
    n_params = design.shape[1]
    weights = np.zeros(n_params, dtype=np.float64)
    weights[0] = _logit(float(np.clip(y.mean(), 1e-6, 1 - 1e-6)))

    penalty = np.full(n_params, RIDGE, dtype=np.float64)
    penalty[0] = 0.0

    for _ in range(MAX_ITERATIONS):
        eta = design @ weights
        mu = _sigmoid(eta)
        variance = np.clip(mu * (1.0 - mu), 1e-8, None)

        gradient = design.T @ (y - mu) - penalty * weights
        hessian = -(design.T * variance) @ design - np.diag(penalty)

        try:
            step = np.linalg.solve(hessian, -gradient)
        except np.linalg.LinAlgError:
            step = np.linalg.lstsq(hessian, -gradient, rcond=None)[0]

        # Damped update: a full Newton step on separable data overshoots badly on the first pass.
        weights = weights + np.clip(step, -2.0, 2.0)
        if np.max(np.abs(step)) < 1e-8:
            break

    return weights
